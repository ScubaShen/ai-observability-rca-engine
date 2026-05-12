import json

from rca_engine.evaluation.metrics import (
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    root_cause_at_k,
)
from rca_engine.evaluation.runner import run_evaluation
from rca_engine.models import KnowledgeMatch


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


def test_eval_runner_smoke_test(tmp_path):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "runbooks.json").write_text(
        json.dumps(
            [
                {
                    "runbook_id": "rb-1",
                    "title": "Application exception investigation",
                    "categories": ["application"],
                    "keywords": ["exception"],
                    "steps": ["Inspect logs."],
                }
            ]
        ),
        encoding="utf-8",
    )
    (fixture_dir / "rag_documents.json").write_text(
        json.dumps(
            [
                {
                    "document_id": "doc_1",
                    "source_type": "rca_result",
                    "ref_id": "incident_1",
                    "incident_id": "incident_1",
                    "title": "Application exception RCA",
                    "content": "Application exception with trace evidence.",
                    "metadata": {"evidence_event_ids": ["event_1"]},
                }
            ]
        ),
        encoding="utf-8",
    )
    (fixture_dir / "rca_results.json").write_text(
        json.dumps(
            [
                {
                    "incident_id": "incident_1",
                    "root_causes": [{"category": "application", "title": "Application exception"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    for name in ("agent_reports.json", "incident_graphs.json", "events.json"):
        (fixture_dir / name).write_text("[]", encoding="utf-8")

    dataset = tmp_path / "queries.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "query_id": "q1",
                "query": "application exception",
                "incident_id": "incident_1",
                "relevant_document_ids": ["doc_1"],
                "relevant_evidence_ids": ["event_1"],
                "expected_root_cause_categories": ["application"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_evaluation(dataset, dataset, fixture_dir)

    assert report.rag.query_count == 1
    assert report.rag.recall_at_5 == 1.0
    assert report.rca.root_cause_at_3 == 1.0
    assert report.queries[0].verification_status in {"confirmed", "likely"}
