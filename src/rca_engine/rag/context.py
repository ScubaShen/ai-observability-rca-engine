from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rca_engine.models import Citation, KnowledgeMatch


@dataclass(frozen=True)
class BuiltContext:
    matches: list[KnowledgeMatch]
    citations: list[Citation]
    trace: dict[str, Any] = field(default_factory=dict)


class ContextBuilder:
    def build(self, matches: list[KnowledgeMatch], limit: int = 5) -> BuiltContext:
        selected = _select_diverse_sources(matches, limit)
        citations = [_citation_from_match(match) for match in selected]
        evidence_coverage = _evidence_coverage(selected, citations)
        trace = {
            "selected_count": len(selected),
            "source_diversity": len({match.source for match in selected}),
            "evidence_coverage": evidence_coverage,
            "selected_sources": [match.source for match in selected],
        }
        return BuiltContext(matches=selected, citations=citations, trace=trace)


def _select_diverse_sources(matches: list[KnowledgeMatch], limit: int) -> list[KnowledgeMatch]:
    selected: list[KnowledgeMatch] = []
    seen_sources: set[str] = set()
    for match in matches:
        if len(selected) >= limit:
            break
        if match.source in seen_sources:
            continue
        selected.append(match)
        seen_sources.add(match.source)
    for match in matches:
        if len(selected) >= limit:
            break
        if match not in selected:
            selected.append(match)
    return selected


def _citation_from_match(match: KnowledgeMatch) -> Citation:
    evidence_ids = match.attributes.get("evidence_event_ids") or match.attributes.get("event_ids") or []
    if isinstance(evidence_ids, str):
        evidence_ids = [evidence_ids]
    return Citation(
        source=match.source,
        ref_id=match.ref_id,
        title=match.title,
        evidence_ids=list(evidence_ids)[:10],
        quote=_snippet(match.content),
    )


def _snippet(content: str, limit: int = 240) -> str:
    compact = " ".join(content.split())
    return compact[:limit]


def _evidence_coverage(matches: list[KnowledgeMatch], citations: list[Citation]) -> float:
    expected_ids: set[str] = set()
    for match in matches:
        ids = match.attributes.get("evidence_event_ids") or match.attributes.get("event_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        expected_ids.update(str(item) for item in ids if item)
    if not expected_ids:
        return 1.0 if citations else 0.0
    cited_ids = {item for citation in citations for item in citation.evidence_ids}
    return round(len(expected_ids.intersection(cited_ids)) / len(expected_ids), 4)
