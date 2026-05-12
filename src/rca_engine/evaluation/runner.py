from __future__ import annotations

import argparse
import json
from pathlib import Path

from rca_engine.evaluation.comparison import compare_reports
from rca_engine.evaluation.metrics import (
    average,
    citation_coverage,
    evidence_support,
    matched_relevant_ids,
    ndcg_at_k,
    p95,
    recall_at_k,
    reciprocal_rank,
    relevant_ids_for_query,
    root_cause_at_k,
    supporting_evidence_ids,
)
from rca_engine.evaluation.replay import run_replay
from rca_engine.evaluation.replay_store import ReplayStore
from rca_engine.evaluation.schemas import (
    EvaluationCase,
    EvaluationReport,
    QueryEvaluationResult,
    RAGMetricBlock,
    RCAEvaluationResult,
    RCAMetricBlock,
    SliceMetricBlock,
)
from rca_engine.models import CopilotRequest, RCAResult
from rca_engine.rag.copilot import RCACopilot


def run_replay_evaluation(
    *,
    rag_dataset: Path,
    rca_dataset: Path,
    events: Path,
    runbooks: Path,
    output: Path | None = None,
) -> EvaluationReport:
    replay = run_replay(events_path=events, runbooks_path=runbooks)
    rag_cases = _load_dataset(rag_dataset)
    rca_cases = _load_dataset(rca_dataset)
    copilot = RCACopilot(replay.store)

    query_results = [_evaluate_rag_query(copilot, query) for query in rag_cases]
    rca_results = [_evaluate_rca_case(replay.store, query) for query in rca_cases]
    report = EvaluationReport(
        rag=_rag_metrics(query_results),
        rca=_rca_metrics(rca_results),
        slices=_slice_metrics(query_results, rca_results),
        queries=query_results,
        rca_cases=rca_results,
        replay=replay.summary,
        metadata={
            "rag_dataset": str(rag_dataset),
            "rca_dataset": str(rca_dataset),
            "events": str(events),
            "runbooks": str(runbooks),
            "mode": "replay",
        },
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run replay-first RCA/RAG evaluation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser("replay", help="Replay NormalizedEvent fixtures and evaluate RCA/RAG.")
    replay_parser.add_argument("--rag-dataset", type=Path, required=True)
    replay_parser.add_argument("--rca-dataset", type=Path, required=True)
    replay_parser.add_argument("--events", type=Path, required=True)
    replay_parser.add_argument("--runbooks", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path)

    compare_parser = subparsers.add_parser("compare", help="Compare two replay eval reports.")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "replay":
        report = run_replay_evaluation(
            rag_dataset=args.rag_dataset,
            rca_dataset=args.rca_dataset,
            events=args.events,
            runbooks=args.runbooks,
            output=args.output,
        )
        print(report.model_dump_json(indent=2))
        return 0
    if args.command == "compare":
        report = compare_reports(args.baseline, args.candidate, args.output)
        print(report.model_dump_json(indent=2))
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _evaluate_rag_query(copilot: RCACopilot, query: EvaluationCase) -> QueryEvaluationResult:
    response = copilot.answer(
        CopilotRequest(
            question=query.query,
            incident_id=query.incident_id,
            limit=10,
            mode="fast",
        )
    )
    relevant_ids = relevant_ids_for_query(
        query.relevant_document_ids,
        query.relevant_sources,
        query.relevant_evidence_ids,
        query.relevant_runbook_ids,
    )
    retrieved_ids = matched_relevant_ids(response.matches[:10], relevant_ids)
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
        incident_id=query.incident_id,
        intent=query.intent,
        metric_slices=_case_slices(query),
        top_refs=[str(item.ref_id or item.attributes.get("document_id") or item.title) for item in response.matches[:10]],
        top_sources=[item.source for item in response.matches[:10]],
        retrieved_expected_ids=sorted(retrieved_ids),
        missed_expected_ids=sorted(relevant_ids - retrieved_ids),
        recall_at_5=recall_at_k(response.matches, relevant_ids, 5),
        recall_at_10=recall_at_k(response.matches, relevant_ids, 10),
        mrr=reciprocal_rank(response.matches, relevant_ids, 10),
        ndcg_at_5=ndcg_at_k(response.matches, relevant_ids, 5),
        citation_coverage=citation_score,
        unsupported=unsupported,
        latency_ms=response.latency_ms or 0,
        verification_status=verification.status if verification else None,
    )


def _evaluate_rca_case(store: ReplayStore, query: EvaluationCase) -> RCAEvaluationResult:
    row = store.get_rca_result(query.incident_id or "") if query.incident_id else None
    result = RCAResult.model_validate(row) if row else None
    categories = [root.category for root in result.root_causes] if result else []
    hypotheses = [root.title for root in result.root_causes] if result else []
    expected_categories = set(query.expected_root_cause_categories)
    expected_evidence_ids = set(query.relevant_evidence_ids)
    support = evidence_support(result, expected_evidence_ids)
    supporting_ids = supporting_evidence_ids(result) if result else set()
    unsupported = bool(result and result.root_causes and support == 0 and expected_evidence_ids)
    if not result:
        unsupported = True
    return RCAEvaluationResult(
        query_id=query.query_id,
        incident_id=query.incident_id,
        metric_slices=_case_slices(query),
        expected_categories=sorted(expected_categories),
        top_categories=categories[:3],
        top_hypotheses=hypotheses[:3],
        supporting_evidence_ids=sorted(supporting_ids),
        missed_evidence_ids=sorted(expected_evidence_ids - supporting_ids),
        root_cause_at_1=root_cause_at_k(categories, expected_categories, 1),
        root_cause_at_3=root_cause_at_k(categories, expected_categories, 3),
        category_accuracy=root_cause_at_k(categories, expected_categories, 1),
        evidence_support=support,
        unsupported_root_cause=unsupported,
    )


def _rag_metrics(results: list[QueryEvaluationResult]) -> RAGMetricBlock:
    return RAGMetricBlock(
        query_count=len(results),
        recall_at_5=average([item.recall_at_5 for item in results]),
        recall_at_10=average([item.recall_at_10 for item in results]),
        mrr=average([item.mrr for item in results]),
        ndcg_at_5=average([item.ndcg_at_5 for item in results]),
        citation_coverage=average([item.citation_coverage for item in results]),
        unsupported_answer_rate=average([1.0 if item.unsupported else 0.0 for item in results]),
        p95_latency_ms=p95([item.latency_ms for item in results]),
    )


def _rca_metrics(results: list[RCAEvaluationResult]) -> RCAMetricBlock:
    return RCAMetricBlock(
        case_count=len(results),
        root_cause_at_1=average([item.root_cause_at_1 for item in results]),
        root_cause_at_3=average([item.root_cause_at_3 for item in results]),
        category_accuracy=average([item.category_accuracy for item in results]),
        evidence_support=average([item.evidence_support for item in results]),
        unsupported_root_cause_rate=average([1.0 if item.unsupported_root_cause else 0.0 for item in results]),
    )


def _slice_metrics(
    rag_results: list[QueryEvaluationResult],
    rca_results: list[RCAEvaluationResult],
) -> dict[str, SliceMetricBlock]:
    names = sorted({name for item in rag_results for name in item.metric_slices}.union(
        {name for item in rca_results for name in item.metric_slices}
    ))
    slices: dict[str, SliceMetricBlock] = {}
    for name in names:
        slices[name] = SliceMetricBlock(
            rag=_rag_metrics([item for item in rag_results if name in item.metric_slices]),
            rca=_rca_metrics([item for item in rca_results if name in item.metric_slices]),
        )
    return slices


def _case_slices(case: EvaluationCase) -> list[str]:
    values = {case.intent, case.dataset_split, *case.metric_slices}
    values.update(case.expected_root_cause_categories)
    if any(ord(char) > 127 for char in case.query):
        values.add("chinese")
    elif case.query:
        values.add("english")
    return sorted(item for item in values if item)


def _load_dataset(path: Path) -> list[EvaluationCase]:
    rows: list[EvaluationCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(EvaluationCase.model_validate(json.loads(line)))
    return rows
