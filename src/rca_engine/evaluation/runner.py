from __future__ import annotations

import argparse
import json
from pathlib import Path

from rca_engine.evaluation.fixture_store import EvaluationFixtureStore
from rca_engine.evaluation.metrics import (
    average,
    citation_coverage,
    ndcg_at_k,
    p95,
    recall_at_k,
    reciprocal_rank,
    relevant_ids_for_query,
    root_cause_at_k,
)
from rca_engine.evaluation.schemas import (
    EvaluationQuery,
    EvaluationReport,
    MetricBlock,
    QueryEvaluationResult,
    RCAMetricBlock,
)
from rca_engine.models import CopilotRequest
from rca_engine.rag.copilot import RCACopilot


def run_evaluation(
    rag_dataset: Path,
    rca_dataset: Path,
    fixture_dir: Path,
    output: Path | None = None,
) -> EvaluationReport:
    store = EvaluationFixtureStore(fixture_dir)
    copilot = RCACopilot(store)
    rag_queries = _load_dataset(rag_dataset)
    rca_queries = _load_dataset(rca_dataset)

    query_results = [_evaluate_rag_query(copilot, query) for query in rag_queries]
    rca_scores = [_evaluate_rca_case(store, query) for query in rca_queries]

    report = EvaluationReport(
        rag=MetricBlock(
            query_count=len(query_results),
            recall_at_5=average([item.recall_at_5 for item in query_results]),
            mrr=average([item.mrr for item in query_results]),
            ndcg_at_5=average([item.ndcg_at_5 for item in query_results]),
            citation_coverage=average([item.citation_coverage for item in query_results]),
            unsupported_answer_rate=average([1.0 if item.unsupported else 0.0 for item in query_results]),
            p95_latency_ms=p95([item.latency_ms for item in query_results]),
        ),
        rca=RCAMetricBlock(
            case_count=len(rca_scores),
            root_cause_at_3=average(rca_scores),
        ),
        queries=query_results,
        metadata={
            "rag_dataset": str(rag_dataset),
            "rca_dataset": str(rca_dataset),
            "fixtures": str(fixture_dir),
            "mode": "offline_deterministic",
        },
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline RCA/RAG evaluation.")
    parser.add_argument("--rag-dataset", type=Path, required=True)
    parser.add_argument("--rca-dataset", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_evaluation(args.rag_dataset, args.rca_dataset, args.fixtures, args.output)
    print(report.model_dump_json(indent=2))
    return 0


def _evaluate_rag_query(copilot: RCACopilot, query: EvaluationQuery) -> QueryEvaluationResult:
    response = copilot.answer(
        CopilotRequest(
            question=query.query,
            incident_id=query.incident_id,
            limit=5,
            mode="fast",
        )
    )
    relevant_ids = relevant_ids_for_query(
        query.relevant_document_ids,
        query.relevant_sources,
        query.relevant_evidence_ids,
        query.relevant_runbook_ids,
    )
    citation_score = citation_coverage(response.citations, set(query.relevant_evidence_ids))
    verification = response.verification
    unsupported = bool(
        verification
        and (
            verification.status == "missing_evidence"
            or verification.hallucination_risk == "high"
            or (query.relevant_evidence_ids and not response.citations)
        )
    )
    return QueryEvaluationResult(
        query_id=query.query_id,
        top_refs=[str(item.ref_id or item.attributes.get("document_id") or item.title) for item in response.matches[:5]],
        top_sources=[item.source for item in response.matches[:5]],
        recall_at_5=recall_at_k(response.matches, relevant_ids, 5),
        mrr=reciprocal_rank(response.matches, relevant_ids, 5),
        ndcg_at_5=ndcg_at_k(response.matches, relevant_ids, 5),
        citation_coverage=citation_score,
        unsupported=unsupported,
        latency_ms=response.latency_ms or 0,
        verification_status=verification.status if verification else None,
    )


def _evaluate_rca_case(store: EvaluationFixtureStore, query: EvaluationQuery) -> float:
    if not query.incident_id:
        return 0.0
    result = store.get_rca_result(query.incident_id) or {}
    categories = [str(item.get("category")) for item in result.get("root_causes", []) if item.get("category")]
    return root_cause_at_k(categories, set(query.expected_root_cause_categories), 3)


def _load_dataset(path: Path) -> list[EvaluationQuery]:
    rows: list[EvaluationQuery] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(EvaluationQuery.model_validate(json.loads(line)))
    return rows
