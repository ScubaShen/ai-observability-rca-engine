from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.planner import RetrievalPlan
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

RRF_K = 60
RRF_WEIGHT = 0.7
BOOST_WEIGHT = 0.3


@dataclass
class _FusedCandidate:
    match: KnowledgeMatch
    channel_ranks: dict[str, int] = field(default_factory=dict)
    channel_scores: dict[str, float] = field(default_factory=dict)
    recall_sources: set[str] = field(default_factory=set)


class RRFFusionRanker:
    def __init__(self, rrf_k: int = RRF_K) -> None:
        self.rrf_k = rrf_k

    def rerank(
        self,
        channel_matches: dict[str, list[KnowledgeMatch]],
        plan: RetrievalPlan,
    ) -> list[KnowledgeMatch]:
        fused = self._fuse(channel_matches)
        if not fused:
            return []
        raw_scores = {
            key: _rrf_score(candidate.channel_ranks, self.rrf_k)
            for key, candidate in fused.items()
        }
        max_raw_score = max(raw_scores.values()) or 1.0
        ranked: list[KnowledgeMatch] = []
        for key, candidate in fused.items():
            rrf_score = raw_scores[key] / max_raw_score
            boost_breakdown = _domain_boost(candidate.match, plan)
            boost_score = min(sum(boost_breakdown.values()), 1.0)
            final_score = min((rrf_score * RRF_WEIGHT) + (boost_score * BOOST_WEIGHT), 1.0)
            breakdown = dict(candidate.match.score_breakdown)
            breakdown.update(
                {
                    "rrf_score": round(rrf_score, 4),
                    "source_rank_score": round(rrf_score * RRF_WEIGHT, 4),
                    "final_boost_score": round(boost_score * BOOST_WEIGHT, 4),
                    **{name: round(value, 4) for name, value in boost_breakdown.items()},
                }
            )
            attributes: dict[str, Any] = dict(candidate.match.attributes)
            attributes["retrieval_channel_ranks"] = dict(sorted(candidate.channel_ranks.items()))
            attributes["retrieval_channel_scores"] = {
                name: round(value, 4) for name, value in sorted(candidate.channel_scores.items())
            }
            ranked.append(
                candidate.match.model_copy(
                    update={
                        "score": round(final_score, 4),
                        "score_breakdown": breakdown,
                        "recall_sources": sorted(candidate.recall_sources),
                        "attributes": attributes,
                    }
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    def _fuse(
        self,
        channel_matches: dict[str, list[KnowledgeMatch]],
    ) -> dict[tuple[str, str], _FusedCandidate]:
        fused: dict[tuple[str, str], _FusedCandidate] = {}
        for channel, matches in channel_matches.items():
            seen_in_channel: set[tuple[str, str]] = set()
            for rank, match in enumerate(matches, start=1):
                key = _dedupe_key(match)
                if key in seen_in_channel:
                    continue
                seen_in_channel.add(key)
                existing = fused.get(key)
                if not existing:
                    existing = _FusedCandidate(match=match)
                    fused[key] = existing
                elif match.score > existing.match.score:
                    existing.match = _merge_match(match, existing.match)
                else:
                    existing.match = _merge_match(existing.match, match)
                existing.channel_ranks[channel] = rank
                existing.channel_scores[channel] = max(
                    existing.channel_scores.get(channel, 0.0),
                    match.score,
                )
                existing.recall_sources.update(match.recall_sources or [])
                existing.recall_sources.add(channel)
        return fused


def rerank(matches: list[KnowledgeMatch], intent: QueryIntent) -> list[KnowledgeMatch]:
    ranked: list[KnowledgeMatch] = []
    for match in matches:
        breakdown = dict(match.score_breakdown)
        semantic_score = breakdown.get(
            "semantic_score",
            match.score if "semantic" in match.recall_sources else 0.0,
        )
        keyword_score = breakdown.get(
            "keyword_score",
            match.score if "keyword" in match.recall_sources else 0.0,
        )
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
        incident_match_score = (
            0.12 if attrs.get("incident_id") and match.ref_id == attrs.get("incident_id") else 0.0
        )
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


def _rrf_score(channel_ranks: dict[str, int], rrf_k: int) -> float:
    return sum(1.0 / (rrf_k + rank) for rank in channel_ranks.values())


def _dedupe_key(match: KnowledgeMatch) -> tuple[str, str]:
    return (match.source, str(match.ref_id or match.attributes.get("document_id") or match.title))


def _merge_match(primary: KnowledgeMatch, secondary: KnowledgeMatch) -> KnowledgeMatch:
    attributes = dict(secondary.attributes)
    attributes.update(primary.attributes)
    breakdown = dict(secondary.score_breakdown)
    breakdown.update(primary.score_breakdown)
    return primary.model_copy(
        update={
            "attributes": attributes,
            "score_breakdown": breakdown,
            "recall_sources": sorted(set(primary.recall_sources + secondary.recall_sources)),
        }
    )


def _domain_boost(match: KnowledgeMatch, plan: RetrievalPlan) -> dict[str, float]:
    attrs = match.attributes
    service_env_score = 0.0
    service = plan.entities.get("service") or plan.intent.service
    env = plan.entities.get("env") or plan.intent.env
    if service and attrs.get("service") == service:
        service_env_score += 0.12
    if env and attrs.get("env") == env:
        service_env_score += 0.08

    incident_match_score = 0.0
    incident_id = plan.incident_id
    if incident_id and (match.ref_id == incident_id or attrs.get("incident_id") == incident_id):
        incident_match_score = 0.12

    intent_score = 0.0
    if plan.intent.intent == "runbook" and match.source == "runbook":
        intent_score += 0.18
    if plan.intent.intent == "evidence" and match.source in {
        "evidence_summary",
        "normalized_event",
        "rca_result",
    }:
        intent_score += 0.14
    if plan.intent.intent in {"root_cause", "postmortem"} and match.source in {
        "rca_result",
        "evidence_summary",
    }:
        intent_score += 0.08
    if plan.intent.intent == "similar_incident" and match.source == "historical_incident":
        intent_score += 0.18

    evidence_strength_score = 0.0
    if attrs.get("evidence_strength") == "strong":
        evidence_strength_score = 0.12
    elif attrs.get("evidence_event_ids") or attrs.get("event_ids"):
        evidence_strength_score = 0.06

    severity_score = 0.04 if attrs.get("severity") in {"critical", "error"} else 0.0
    source_priority_score = min(SOURCE_WEIGHTS.get(match.source, 0.0), 0.08)
    return {
        "service_env_score": service_env_score,
        "incident_match_score": incident_match_score,
        "intent_score": intent_score,
        "evidence_strength_score": evidence_strength_score,
        "severity_score": severity_score,
        "source_priority_score": source_priority_score,
    }
