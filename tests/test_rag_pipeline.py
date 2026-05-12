from rca_engine.models import KnowledgeMatch
from rca_engine.rag.candidates import CandidateProcessor
from rca_engine.rag.context import ContextBuilder
from rca_engine.rag.preprocessor import DriftChecker, QueryPreprocessor


def test_query_preprocessor_extracts_entities_and_bounded_rewrite_preserves_them():
    processed = QueryPreprocessor().process(
        "Why did service=checkout env=prod fail for incident_123 trace_checkout_1 NullPointerException?"
    )

    assert processed.entities["service"] == "checkout"
    assert processed.entities["env"] == "prod"
    assert processed.entities["incident_id"] == "incident_123"
    assert processed.entities["trace_id"] == "trace_checkout_1"
    assert processed.entities["error_code"] == "NullPointerException"
    assert "incident_123" in processed.rewritten_query
    assert processed.drift_detected is False


def test_drift_checker_rejects_rewrite_that_drops_original_terms():
    checker = DriftChecker()

    assert checker.has_drift("checkout exception trace_1", "unrelated summary", {"trace_id": "trace_1"})


def test_candidate_processor_dedupes_and_merges_recall_sources():
    first = KnowledgeMatch(
        source="rca_result",
        title="Checkout RCA",
        score=0.4,
        content="first",
        ref_id="incident_1",
        attributes={"document_id": "doc_1"},
        score_breakdown={"keyword_score": 0.4},
        recall_sources=["keyword"],
    )
    second = first.model_copy(
        update={
            "score": 0.7,
            "content": "second",
            "score_breakdown": {"semantic_score": 0.7},
            "recall_sources": ["semantic"],
        }
    )

    result = CandidateProcessor().process([first, second])

    assert len(result.matches) == 1
    assert result.matches[0].score == 0.7
    assert set(result.matches[0].recall_sources) == {"keyword", "semantic"}
    assert result.trace["input_count"] == 2
    assert result.trace["deduped_count"] == 1


def test_context_builder_selects_citation_snippets_and_evidence_coverage():
    matches = [
        KnowledgeMatch(
            source="rca_result",
            title="Checkout RCA",
            score=0.9,
            content="Checkout application exception with detailed trace evidence.",
            ref_id="incident_1",
            attributes={"evidence_event_ids": ["event_1"]},
            recall_sources=["keyword"],
        )
    ]

    built = ContextBuilder().build(matches)

    assert built.citations[0].evidence_ids == ["event_1"]
    assert built.citations[0].quote == "Checkout application exception with detailed trace evidence."
    assert built.trace["evidence_coverage"] == 1.0
