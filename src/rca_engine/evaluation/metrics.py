from __future__ import annotations

import math
from statistics import mean

from rca_engine.models import Citation, KnowledgeMatch


def recall_at_k(matches: list[KnowledgeMatch], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    found = _matched_relevant_ids(matches[:k], relevant_ids)
    return round(len(found) / len(relevant_ids), 4)


def reciprocal_rank(matches: list[KnowledgeMatch], relevant_ids: set[str], k: int | None = None) -> float:
    window = matches[:k] if k else matches
    for index, match in enumerate(window, start=1):
        if _match_ids(match).intersection(relevant_ids):
            return round(1 / index, 4)
    return 0.0


def ndcg_at_k(matches: list[KnowledgeMatch], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    gains = [1.0 if _match_ids(match).intersection(relevant_ids) else 0.0 for match in matches[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal_hits = min(len(relevant_ids), k)
    ideal_dcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    if ideal_dcg == 0:
        return 0.0
    return round(dcg / ideal_dcg, 4)


def root_cause_at_k(categories: list[str], expected_categories: set[str], k: int) -> float:
    if not expected_categories:
        return 0.0
    return 1.0 if set(categories[:k]).intersection(expected_categories) else 0.0


def citation_coverage(citations: list[Citation], relevant_evidence_ids: set[str]) -> float:
    if not relevant_evidence_ids:
        return 1.0 if citations else 0.0
    cited_ids = {item for citation in citations for item in citation.evidence_ids}
    return round(len(cited_ids.intersection(relevant_evidence_ids)) / len(relevant_evidence_ids), 4)


def average(values: list[float]) -> float:
    return round(mean(values), 4) if values else 0.0


def p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = math.ceil(0.95 * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def relevant_ids_for_query(
    document_ids: list[str],
    sources: list[str],
    evidence_ids: list[str],
    runbook_ids: list[str],
) -> set[str]:
    return {str(item) for item in [*document_ids, *sources, *evidence_ids, *runbook_ids] if item}


def _matched_relevant_ids(matches: list[KnowledgeMatch], relevant_ids: set[str]) -> set[str]:
    found: set[str] = set()
    for match in matches:
        found.update(_match_ids(match).intersection(relevant_ids))
    return found


def _match_ids(match: KnowledgeMatch) -> set[str]:
    ids = {
        str(match.source),
        str(match.ref_id or ""),
        str(match.title),
        str(match.attributes.get("document_id") or ""),
        str(match.attributes.get("runbook_id") or ""),
    }
    for key in ("evidence_event_ids", "event_ids"):
        values = match.attributes.get(key) or []
        if isinstance(values, str):
            values = [values]
        ids.update(str(value) for value in values if value)
    return {item for item in ids if item}
