import json
from pathlib import Path

from rca_engine.evaluation.comparison import compare_evaluation_reports
from rca_engine.evaluation.metrics import (
    evidence_support,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    root_cause_at_k,
)
from rca_engine.evaluation.replay import run_replay
from rca_engine.evaluation.runner import run_replay_evaluation
from rca_engine.evaluation.schemas import (
    EvaluationCase,
    EvaluationReport,
    QueryEvaluationResult,
    RAGMetricBlock,
    RCAEvaluationResult,
    RCAMetricBlock,
)
from rca_engine.hash_utils import stable_id
from rca_engine.models import KnowledgeMatch, RCAResult


ROOT = Path(__file__).resolve().parents[1]


def match(ref_id, source="rca_result", document_id=None):
    return KnowledgeMatch(
        source=source,
        title=str(ref_id),
        score=0.8,
        content="evidence",
        ref_id=ref_id,
        attributes={"document_id": document_id or ref_id},
        recall_sources=["keyword"],
    )


def test_recall_at_k_handles_perfect_partial_and_zero_hits():
    matches = [match("doc_1"), match("doc_2"), match("doc_3")]

    assert recall_at_k(matches, {"doc_1", "doc_2"}, 2) == 1.0
    assert recall_at_k(matches, {"doc_1", "doc_4"}, 2) == 0.5
    assert recall_at_k(matches, {"doc_4"}, 3) == 0.0


def test_mrr_uses_first_relevant_rank():
    matches = [match("doc_1"), match("doc_2"), match("doc_3")]

    assert reciprocal_rank(matches, {"doc_1"}, 3) == 1.0
    assert reciprocal_rank(matches, {"doc_3"}, 3) == 0.3333
    assert reciprocal_rank(matches, {"doc_4"}, 3) == 0.0


def test_ndcg_rewards_better_ordering():
    ordered = [match("doc_1"), match("doc_2"), match("doc_3")]
    misordered = [match("doc_3"), match("doc_2"), match("doc_1")]

    assert ndcg_at_k(ordered, {"doc_1", "doc_2"}, 3) == 1.0
    assert ndcg_at_k(misordered, {"doc_1", "doc_2"}, 3) < 1.0


def test_root_cause_at_k_hits_expected_category():
    assert root_cause_at_k(["application", "dependency"], {"dependency"}, 3) == 1.0
    assert root_cause_at_k(["resource_or_load"], {"dependency"}, 3) == 0.0


def test_replay_events_generate_incident_rca_and_rag_documents(tmp_path):
    runbooks, events = _write_replay_inputs(tmp_path)

    replay = run_replay(events_path=events, runbooks_path=runbooks)

    assert replay.summary.input_event_count == 2
    assert replay.summary.extracted_event_count == 2
    assert replay.summary.candidate_count == 1
    assert replay.summary.rca_result_count == 1
    assert replay.summary.rag_document_count >= 3

    result = RCAResult.model_validate(replay.store.get_rca_result(_incident_id()))
    assert result.root_causes[0].category == "application"
    assert evidence_support(result, {"event_log_1", "event_trace_1"}) == 1.0

    matches = replay.store.search_rag_documents("checkout application exception", [], incident_id=_incident_id())
    assert matches
    assert {item["source_type"] for item in matches}.intersection({"rca_result", "evidence_summary"})


def test_replay_eval_scores_rag_and_rca(tmp_path):
    runbooks, events = _write_replay_inputs(tmp_path)
    rag_dataset, rca_dataset = _write_datasets(tmp_path)

    report = run_replay_evaluation(
        rag_dataset=rag_dataset,
        rca_dataset=rca_dataset,
        events=events,
        runbooks=runbooks,
    )

    assert report.mode == "replay"
    assert report.rag.query_count == 1
    assert report.rag.recall_at_5 == 1.0
    assert report.rca.case_count == 1
    assert report.rca.root_cause_at_1 == 1.0
    assert report.rca.evidence_support == 1.0
    assert report.queries[0].missed_expected_ids == []
    assert "application" in report.slices


def test_dev_and_holdout_datasets_are_valid_evaluation_cases():
    dataset_paths = [
        ROOT / "eval/datasets/rag_queries.dev.jsonl",
        ROOT / "eval/datasets/rag_queries.holdout.jsonl",
        ROOT / "eval/datasets/rca_queries.dev.jsonl",
        ROOT / "eval/datasets/rca_queries.holdout.jsonl",
    ]

    cases = [_load_case(line) for path in dataset_paths for line in path.read_text().splitlines() if line]

    assert {case.dataset_split for case in cases} == {"dev", "holdout"}
    assert any("chinese_query" in case.metric_slices for case in cases)
    assert any("noisy_query" in case.metric_slices for case in cases)
    assert any("evidence_support" in case.metric_slices for case in cases)


def test_hard_replay_eval_exposes_dev_and_holdout_slices():
    dev_report = run_replay_evaluation(
        rag_dataset=ROOT / "eval/datasets/rag_queries.dev.jsonl",
        rca_dataset=ROOT / "eval/datasets/rca_queries.dev.jsonl",
        events=ROOT / "eval/fixtures/replay_events.hard.json",
        runbooks=ROOT / "eval/fixtures/runbooks.hard.json",
    )
    holdout_report = run_replay_evaluation(
        rag_dataset=ROOT / "eval/datasets/rag_queries.holdout.jsonl",
        rca_dataset=ROOT / "eval/datasets/rca_queries.holdout.jsonl",
        events=ROOT / "eval/fixtures/replay_events.hard.json",
        runbooks=ROOT / "eval/fixtures/runbooks.hard.json",
    )

    assert dev_report.rag.query_count == 6
    assert dev_report.rca.case_count == 4
    assert {"dev", "hard", "chinese_query", "noisy_query", "runbook_discrimination"}.issubset(
        dev_report.slices
    )
    assert holdout_report.rag.query_count == 2
    assert holdout_report.rca.case_count == 1
    assert {"holdout", "hard", "chinese_query", "evidence_support"}.issubset(
        holdout_report.slices
    )


def test_compare_report_self_comparison_is_neutral():
    report = _comparison_report(recall=1.0, rca_hit=1.0, evidence=1.0)

    comparison = compare_evaluation_reports(report, report)

    assert comparison.verdict == "neutral"
    assert comparison.regressions == []


def test_compare_report_detects_regression():
    baseline = _comparison_report(recall=1.0, rca_hit=1.0, evidence=1.0)
    candidate = _comparison_report(recall=0.0, rca_hit=0.0, evidence=0.0)

    comparison = compare_evaluation_reports(baseline, candidate)

    assert comparison.verdict == "regressed"
    assert comparison.regressions


def test_compare_report_needs_review_when_gain_hides_case_regression():
    baseline = _comparison_report(recall=0.5, rca_hit=1.0, evidence=1.0)
    baseline.queries.append(
        QueryEvaluationResult(
            query_id="q2",
            retrieved_expected_ids=["doc_2"],
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr=1.0,
            ndcg_at_5=1.0,
            citation_coverage=1.0,
        )
    )
    candidate = _comparison_report(recall=1.0, rca_hit=1.0, evidence=1.0)
    candidate.queries.append(
        QueryEvaluationResult(
            query_id="q2",
            missed_expected_ids=["doc_2"],
            recall_at_5=0.0,
            recall_at_10=0.0,
            mrr=0.0,
            ndcg_at_5=0.0,
            citation_coverage=1.0,
        )
    )
    baseline.rag.recall_at_5 = 0.75
    candidate.rag.recall_at_5 = 0.8

    comparison = compare_evaluation_reports(baseline, candidate)

    assert comparison.verdict == "needs_review"
    assert comparison.regressions
    assert comparison.improvements


def test_compare_report_detects_hard_case_improvement():
    baseline = _comparison_report(recall=0.5, rca_hit=1.0, evidence=1.0)
    candidate = _comparison_report(recall=0.8, rca_hit=1.0, evidence=1.0)
    baseline.queries[0].metric_slices = ["hard", "dev"]
    candidate.queries[0].metric_slices = ["hard", "dev"]
    baseline.rag.recall_at_5 = 0.5
    candidate.rag.recall_at_5 = 0.8

    comparison = compare_evaluation_reports(baseline, candidate)

    assert comparison.verdict == "improved"
    assert comparison.improvements
    assert comparison.regressions == []


def test_compare_report_needs_review_when_holdout_case_regresses():
    baseline = _comparison_report(recall=0.5, rca_hit=1.0, evidence=1.0)
    candidate = _comparison_report(recall=0.8, rca_hit=1.0, evidence=1.0)
    baseline.queries.append(
        QueryEvaluationResult(
            query_id="holdout_q",
            metric_slices=["holdout", "hard"],
            retrieved_expected_ids=["doc_holdout"],
            recall_at_5=1.0,
            recall_at_10=1.0,
            mrr=1.0,
            ndcg_at_5=1.0,
            citation_coverage=1.0,
        )
    )
    candidate.queries.append(
        QueryEvaluationResult(
            query_id="holdout_q",
            metric_slices=["holdout", "hard"],
            missed_expected_ids=["doc_holdout"],
            recall_at_5=0.0,
            recall_at_10=0.0,
            mrr=0.0,
            ndcg_at_5=0.0,
            citation_coverage=1.0,
        )
    )
    baseline.rag.recall_at_5 = 0.75
    candidate.rag.recall_at_5 = 0.8

    comparison = compare_evaluation_reports(baseline, candidate)

    assert comparison.verdict == "needs_review"
    assert any(item.case_id == "holdout_q" for item in comparison.regressions)
    assert comparison.improvements


def _load_case(line: str) -> EvaluationCase:
    return EvaluationCase.model_validate(json.loads(line))


def _write_replay_inputs(tmp_path):
    runbooks = tmp_path / "runbooks.json"
    runbooks.write_text(
        json.dumps(
            [
                {
                    "runbook_id": "rb-application-exception",
                    "title": "Application exception investigation",
                    "categories": ["application"],
                    "keywords": ["checkout", "exception"],
                    "steps": ["Inspect logs.", "Open the related trace."],
                }
            ]
        ),
        encoding="utf-8",
    )
    events = tmp_path / "replay_events.json"
    events.write_text(
        json.dumps(
            [
                {
                    "event_id": "event_log_1",
                    "event_type": "log.error_pattern",
                    "source_topic": "observability.logs",
                    "event_time": "2026-05-01T10:01:00+00:00",
                    "service": "checkout",
                    "env": "prod",
                    "severity": "error",
                    "trace_id": "trace-checkout-1",
                    "span_id": "span-log-1",
                    "correlation_keys": ["service:checkout", "trace:trace-checkout-1"],
                    "summary": "Checkout failed with java.lang.IllegalStateException.",
                    "attributes": {"error_pattern": "java_exception"},
                },
                {
                    "event_id": "event_trace_1",
                    "event_type": "trace.error",
                    "source_topic": "observability.traces",
                    "event_time": "2026-05-01T10:01:05+00:00",
                    "service": "checkout",
                    "env": "prod",
                    "severity": "error",
                    "trace_id": "trace-checkout-1",
                    "span_id": "span-trace-1",
                    "correlation_keys": ["service:checkout", "trace:trace-checkout-1"],
                    "summary": "Trace error detected on checkout request.",
                    "attributes": {"span_name": "POST /orders", "status_code": "ERROR"},
                },
            ]
        ),
        encoding="utf-8",
    )
    return runbooks, events


def _write_datasets(tmp_path):
    rag_dataset = tmp_path / "rag.jsonl"
    rca_dataset = tmp_path / "rca.jsonl"
    row = {
        "query_id": "q1",
        "query": "checkout application exception",
        "incident_id": _incident_id(),
        "intent": "root_cause",
        "relevant_document_ids": [_incident_id()],
        "relevant_sources": ["rca_result", "evidence_summary"],
        "relevant_evidence_ids": ["event_log_1", "event_trace_1"],
        "relevant_runbook_ids": ["rb-application-exception"],
        "expected_root_cause_categories": ["application"],
        "metric_slices": ["application"],
    }
    rag_dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    rca_dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return rag_dataset, rca_dataset


def _incident_id():
    return stable_id(
        "incident",
        {
            "service": "checkout",
            "env": "prod",
            "window_start": "2026-05-01T10:00:00+00:00",
            "trace_id": "trace-checkout-1",
        },
    )


def _comparison_report(recall: float, rca_hit: float, evidence: float) -> EvaluationReport:
    return EvaluationReport(
        rag=RAGMetricBlock(
            query_count=1,
            recall_at_5=recall,
            recall_at_10=recall,
            mrr=recall,
            ndcg_at_5=recall,
            citation_coverage=1.0,
            unsupported_answer_rate=0.0,
        ),
        rca=RCAMetricBlock(
            case_count=1,
            root_cause_at_1=rca_hit,
            root_cause_at_3=rca_hit,
            category_accuracy=rca_hit,
            evidence_support=evidence,
            unsupported_root_cause_rate=1.0 if evidence == 0 else 0.0,
        ),
        queries=[
            QueryEvaluationResult(
                query_id="q1",
                retrieved_expected_ids=["doc_1"] if recall else [],
                missed_expected_ids=[] if recall else ["doc_1"],
                recall_at_5=recall,
                recall_at_10=recall,
                mrr=recall,
                ndcg_at_5=recall,
                citation_coverage=1.0,
            )
        ],
        rca_cases=[
            RCAEvaluationResult(
                query_id="r1",
                root_cause_at_1=rca_hit,
                root_cause_at_3=rca_hit,
                category_accuracy=rca_hit,
                evidence_support=evidence,
                unsupported_root_cause=evidence == 0,
            )
        ],
    )
