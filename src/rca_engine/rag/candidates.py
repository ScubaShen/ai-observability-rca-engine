from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rca_engine.models import KnowledgeMatch


@dataclass(frozen=True)
class CandidateProcessingResult:
    matches: list[KnowledgeMatch]
    trace: dict[str, Any] = field(default_factory=dict)


class CandidateProcessor:
    def process(self, candidates: list[KnowledgeMatch]) -> CandidateProcessingResult:
        normalized = [_normalize_candidate(candidate) for candidate in candidates]
        deduped = _dedupe(normalized)
        trace = {
            "input_count": len(candidates),
            "normalized_count": len(normalized),
            "deduped_count": len(deduped),
            "source_counts": _source_counts(deduped),
            "recall_source_counts": _recall_source_counts(deduped),
        }
        return CandidateProcessingResult(matches=deduped, trace=trace)


def _normalize_candidate(match: KnowledgeMatch) -> KnowledgeMatch:
    score = max(0.0, min(float(match.score), 1.0))
    breakdown = {key: round(max(0.0, min(float(value), 1.0)), 4) for key, value in match.score_breakdown.items()}
    recall_sources = sorted(set(match.recall_sources or ["heuristic"]))
    attributes = dict(match.attributes)
    attributes.setdefault("source_attribution", match.source)
    return match.model_copy(
        update={
            "score": round(score, 4),
            "score_breakdown": breakdown,
            "recall_sources": recall_sources,
            "attributes": attributes,
        }
    )


def _dedupe(matches: list[KnowledgeMatch]) -> list[KnowledgeMatch]:
    deduped: dict[tuple[str, str], KnowledgeMatch] = {}
    for match in matches:
        key = (match.source, str(match.ref_id or match.attributes.get("document_id") or match.title))
        existing = deduped.get(key)
        if not existing:
            deduped[key] = match
            continue
        primary, secondary = (match, existing) if match.score > existing.score else (existing, match)
        breakdown = dict(secondary.score_breakdown)
        breakdown.update(primary.score_breakdown)
        attributes = dict(secondary.attributes)
        attributes.update(primary.attributes)
        deduped[key] = primary.model_copy(
            update={
                "attributes": attributes,
                "recall_sources": sorted(set(primary.recall_sources + secondary.recall_sources)),
                "score_breakdown": breakdown,
            }
        )
    return list(deduped.values())


def _source_counts(matches: list[KnowledgeMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.source] = counts.get(match.source, 0) + 1
    return counts


def _recall_source_counts(matches: list[KnowledgeMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        for source in match.recall_sources:
            counts[source] = counts.get(source, 0) + 1
    return counts
