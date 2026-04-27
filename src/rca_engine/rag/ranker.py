from __future__ import annotations

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.query import QueryIntent


SOURCE_WEIGHTS = {
    "rca_result": 0.18,
    "agent_report": 0.16,
    "rag_document": 0.14,
    "runbook": 0.12,
    "historical_incident": 0.12,
    "normalized_event": 0.08,
    "graph": 0.06,
}


def rerank(matches: list[KnowledgeMatch], intent: QueryIntent) -> list[KnowledgeMatch]:
    ranked: list[KnowledgeMatch] = []
    for match in matches:
        score = match.score + SOURCE_WEIGHTS.get(match.source, 0.0)
        attrs = match.attributes
        if intent.service and attrs.get("service") == intent.service:
            score += 0.12
        if intent.env and attrs.get("env") == intent.env:
            score += 0.08
        if intent.intent == "runbook" and match.source == "runbook":
            score += 0.18
        if intent.intent == "evidence" and match.source in {"normalized_event", "rca_result"}:
            score += 0.14
        if intent.intent == "similar_incident" and match.source == "historical_incident":
            score += 0.18
        if attrs.get("evidence_strength") == "strong":
            score += 0.12
        if attrs.get("severity") in {"critical", "error"}:
            score += 0.04
        ranked.append(match.model_copy(update={"score": round(min(score, 1.0), 4)}))
    return sorted(ranked, key=lambda item: item.score, reverse=True)
