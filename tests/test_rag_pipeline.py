from rca_engine.models import InvestigationState, KnowledgeMatch, RCAResult
from rca_engine.rag.chunks import chunks_from_rca_result
from rca_engine.rag.candidates import CandidateProcessor
from rca_engine.rag.context import ContextBuilder
from rca_engine.rag.planner import RetrievalPlanner
from rca_engine.rag.preprocessor import DriftChecker, QueryPreprocessor
from rca_engine.rag.query import QueryIntent
from rca_engine.rag.ranker import RRFFusionRanker
from rca_engine.rag.retriever import KnowledgeRetriever
from rca_engine.rag.state import merge_investigation_state
from rca_engine.rag.verification import apply_claim_guardrail, verify_answer


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


def test_query_preprocessor_extracts_observability_entities_for_structured_rewrite():
    processed = QueryPreprocessor().process(
        "Why did service=checkout env=prod metric_name=http.server.duration "
        "POST /checkout fail after deploy_2026_05_12 on v1.2.3 in last 15m?"
    )

    assert processed.entities["service"] == "checkout"
    assert processed.entities["metric_name"] == "http.server.duration"
    assert processed.entities["endpoint"] == "POST /checkout"
    assert processed.entities["deploy_id"] == "deploy_2026_05_12"
    assert processed.entities["version"] == "v1.2.3"
    assert processed.entities["time_range"] == "last 15m"
    assert "http.server.duration" in processed.rewritten_query
    assert "root_cause" in processed.rewritten_query
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


def test_typed_evidence_chunks_keep_event_ids_and_signal_boundaries():
    result = RCAResult(
        incident_id="incident_1",
        service="checkout",
        env="prod",
        severity="error",
        summary="Checkout failed.",
        confidence=0.9,
        evidence=[
            {
                "event_id": "event_metric_1",
                "event_type": "metric.anomaly",
                "category": "metric",
                "signal_type": "latency",
                "service": "checkout",
                "severity": "error",
                "summary": "p95 latency spiked.",
                "confidence": 0.91,
                "strength": "strong",
            }
        ],
    )

    chunks = chunks_from_rca_result(result)

    assert chunks[0].source_type == "evidence_metric"
    assert chunks[0].evidence_ids == ["event_metric_1"]
    assert chunks[0].incident_id == "incident_1"


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
    assert built.evidence_chain[0]["evidence_ids"] == ["event_1"]


def test_rrf_fusion_prefers_multi_channel_consensus_over_single_raw_score():
    shared = KnowledgeMatch(
        source="rca_result",
        title="Shared RCA",
        score=0.2,
        content="shared",
        ref_id="incident_shared",
        attributes={"incident_id": "incident_shared"},
        recall_sources=["keyword"],
    )
    single = KnowledgeMatch(
        source="rca_result",
        title="Single high score RCA",
        score=0.99,
        content="single",
        ref_id="incident_single",
        attributes={"incident_id": "incident_single"},
        recall_sources=["keyword"],
    )
    plan = _plan("root_cause")

    ranked = RRFFusionRanker().rerank(
        {
            "keyword": [single, shared],
            "semantic": [shared],
        },
        plan,
    )

    assert ranked[0].ref_id == "incident_shared"
    assert ranked[0].score_breakdown["rrf_score"] == 1.0
    assert ranked[0].attributes["retrieval_channel_ranks"] == {"keyword": 2, "semantic": 1}


def test_rrf_domain_boost_prefers_matching_service_when_retrieval_is_close():
    mismatch = KnowledgeMatch(
        source="rca_result",
        title="Payment RCA",
        score=0.9,
        content="payment",
        ref_id="incident_payment",
        attributes={"service": "payment", "incident_id": "incident_payment"},
        recall_sources=["semantic"],
    )
    match = KnowledgeMatch(
        source="rca_result",
        title="Checkout RCA",
        score=0.8,
        content="checkout",
        ref_id="incident_checkout",
        attributes={"service": "checkout", "incident_id": "incident_checkout"},
        recall_sources=["semantic"],
    )
    plan = _plan("root_cause", entities={"service": "checkout"})

    ranked = RRFFusionRanker().rerank({"semantic": [mismatch, match]}, plan)

    assert ranked[0].ref_id == "incident_checkout"
    assert ranked[0].score_breakdown["service_env_score"] == 0.12


def test_rrf_boosts_current_evidence_over_generic_historical_context():
    evidence = KnowledgeMatch(
        source="evidence_metric",
        title="Current metric spike",
        score=0.5,
        content="latency spike",
        ref_id="incident_current",
        attributes={"incident_id": "incident_current", "evidence_event_ids": ["event_1"]},
        recall_sources=["current_evidence"],
    )
    historical = KnowledgeMatch(
        source="historical_incident",
        title="Similar previous incident",
        score=0.9,
        content="previous latency spike",
        ref_id="historical_1",
        attributes={"incident_id": "incident_old"},
        recall_sources=["historical"],
    )
    plan = _plan("root_cause", entities={"service": "checkout"})
    plan.incident_id = "incident_current"

    ranked = RRFFusionRanker().rerank(
        {"current_evidence": [evidence], "historical": [historical]},
        plan,
    )

    assert ranked[0].source == "evidence_metric"
    assert ranked[0].score_breakdown["current_evidence_score"] == 0.12


def test_retrieval_planner_adds_aliases_and_domain_expansions_for_noisy_queries():
    processed = QueryPreprocessor().process(
        "Billing says cartsrv hangs after basket lock waiting during rollout"
    )

    plan = RetrievalPlanner().build(processed, incident_id=None, limit=5)

    assert plan.entities["service"] == "cart"
    assert plan.aliases["cartsrv"] == "cart"
    assert plan.aliases["basket"] == "cart"
    assert "cart" in plan.keyword_query
    assert "cache saturation" in plan.semantic_query
    assert "config change" in plan.semantic_query


def test_retriever_ranks_specific_runbooks_before_generic_exception_guide():
    class RunbookStore:
        def list_runbooks(self):
            return [
                {
                    "runbook_id": "rb-application-exception",
                    "title": "Application exception investigation",
                    "categories": ["application"],
                    "keywords": ["exception"],
                    "steps": ["Inspect stack traces."],
                },
                {
                    "runbook_id": "rb-cache-saturation",
                    "title": "Cache saturation and lock contention",
                    "categories": ["dependency"],
                    "keywords": ["cache", "locking", "waiting", "redis"],
                    "steps": ["Inspect queue depth and lock wait."],
                },
                {
                    "runbook_id": "rb-deploy-config-change",
                    "title": "Deploy and config change investigation",
                    "categories": ["change"],
                    "keywords": ["release", "rollout", "config"],
                    "steps": ["Compare rollout and config timing."],
                },
            ]

        def search_rag_documents(self, query, embedding, incident_id=None, limit=10):
            return []

        def latest_rca_results(self, limit=10):
            return []

        def latest_agent_reports(self, limit=10):
            return []

    matches = KnowledgeRetriever(RunbookStore()).search(
        "exceptions slow waiting release timing cache locking downstream calls",
        limit=5,
    )

    runbook_ids = [match.ref_id for match in matches if match.source == "runbook"]
    assert runbook_ids[:2] == ["rb-cache-saturation", "rb-deploy-config-change"]
    assert "rb-application-exception" not in runbook_ids[:2]


def test_claim_guardrail_marks_answers_without_evidence_ids_as_risky():
    citations = [
        type(
            "CitationLike",
            (),
            {
                "source": "evidence_metric",
                "title": "Metric spike",
                "evidence_ids": ["event_1"],
            },
        )()
    ]

    answer, notes = apply_claim_guardrail("Latency increased after deploy.", citations)
    verification = verify_answer(answer, [], citations)

    assert notes
    assert "event_1" in answer
    assert verification.hallucination_risk == "high"


def test_investigation_state_merge_dedupes_and_excludes_hypotheses():
    current = InvestigationState(
        session_id="s1",
        active_hypotheses=["cache saturation", "deploy regression"],
        selected_evidence_ids=["event_1"],
    )
    update = InvestigationState(
        session_id="s1",
        confirmed_facts=["latency spike"],
        excluded_hypotheses=["cache saturation"],
        selected_evidence_ids=["event_1", "event_2"],
    )

    merged = merge_investigation_state(current, update)

    assert merged.confirmed_facts == ["latency spike"]
    assert merged.active_hypotheses == ["deploy regression"]
    assert merged.selected_evidence_ids == ["event_1", "event_2"]


def _plan(intent: str, entities: dict[str, str] | None = None):
    query_intent = QueryIntent(intent=intent)
    return type(
        "Plan",
        (),
        {
            "intent": query_intent,
            "entities": entities or {},
            "incident_id": None,
        },
    )()
