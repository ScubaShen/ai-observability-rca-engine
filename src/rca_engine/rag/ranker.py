from __future__ import annotations

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.query import QueryIntent


SOURCE_WEIGHTS = {
    "rca_result": 0.18,
    "agent_report": 0.16,
    "evidence_summary": 0.15,
    "rag_document": 0.14,
    "runbook": 0.12,
    "historical_incident": 0.12,
    "normalized_event": 0.08,
    "graph": 0.06,
}


def rerank(matches: list[KnowledgeMatch], intent: QueryIntent) -> list[KnowledgeMatch]:
    ranked: list[KnowledgeMatch] = []
    for match in matches:
        breakdown = dict(match.score_breakdown)
        semantic_score = breakdown.get("semantic_score", match.score if "semantic" in match.recall_sources else 0.0)
        keyword_score = breakdown.get("keyword_score", match.score if "keyword" in match.recall_sources else 0.0)
        exact_match_score = breakdown.get("exact_match_score", 0.0)
        base_score = max(match.score, semantic_score, keyword_score, exact_match_score)
        source_priority_score = SOURCE_WEIGHTS.get(match.source, 0.0)
        score = base_score + source_priority_score
        attrs = match.attributes
        service_env_score = 0.0
        if intent.service and attrs.get("service") == intent.service:
            service_env_score += 0.12
        if intent.env and attrs.get("env") == intent.env:
            service_env_score += 0.08
        incident_match_score = 0.12 if attrs.get("incident_id") and match.ref_id == attrs.get("incident_id") else 0.0
        intent_score = 0.0
        if intent.intent == "runbook" and match.source == "runbook":
            intent_score += 0.18
        if intent.intent == "evidence" and match.source in {"normalized_event", "rca_result"}:
            intent_score += 0.14
        if intent.intent == "similar_incident" and match.source == "historical_incident":
            intent_score += 0.18
        evidence_strength_score = 0.0
        if attrs.get("evidence_strength") == "strong":
            evidence_strength_score = 0.12
        severity_score = 0.0
        if attrs.get("severity") in {"critical", "error"}:
            severity_score = 0.04
        score += (
            service_env_score
            + incident_match_score
            + intent_score
            + evidence_strength_score
            + severity_score
        )
        breakdown.update(
            {
                "semantic_score": round(semantic_score, 4),
                "keyword_score": round(keyword_score, 4),
                "exact_match_score": round(exact_match_score, 4),
                "service_env_score": round(service_env_score, 4),
                "incident_match_score": round(incident_match_score, 4),
                "severity_score": round(severity_score, 4),
                "source_priority_score": round(source_priority_score, 4),
                "evidence_strength_score": round(evidence_strength_score, 4),
                "intent_score": round(intent_score, 4),
            }
        )
        ranked.append(
            match.model_copy(
                update={
                    "score": round(min(score, 1.0), 4),
                    "score_breakdown": breakdown,
                    "recall_sources": sorted(set(match.recall_sources or ["heuristic"])),
                }
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)
