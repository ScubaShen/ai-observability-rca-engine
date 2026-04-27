from __future__ import annotations

from rca_engine.models import Citation, KnowledgeMatch, VerificationResult


FORBIDDEN_TERMS = [
    "rollback automatically",
    "auto rollback",
    "restart automatically",
    "auto restart",
    "scale automatically",
    "auto scale",
    "execute ticket",
    "create ticket automatically",
]


def citations_from_matches(matches: list[KnowledgeMatch], limit: int = 5) -> list[Citation]:
    citations: list[Citation] = []
    for match in matches[:limit]:
        evidence_ids = match.attributes.get("evidence_event_ids") or match.attributes.get("event_ids") or []
        if isinstance(evidence_ids, str):
            evidence_ids = [evidence_ids]
        citations.append(
            Citation(
                source=match.source,
                ref_id=match.ref_id,
                title=match.title,
                evidence_ids=list(evidence_ids)[:10],
                quote=match.content[:240],
            )
        )
    return citations


def verify_answer(answer: str, matches: list[KnowledgeMatch], citations: list[Citation]) -> VerificationResult:
    lowered = answer.lower()
    blocked = [term for term in FORBIDDEN_TERMS if term in lowered]
    coverage = _citation_coverage(answer, citations)
    notes: list[str] = []
    if not matches:
        status = "missing_evidence"
        notes.append("No retrieved evidence was available for this answer.")
    elif matches[0].score >= 0.78 and citations:
        status = "confirmed"
    elif matches[0].score >= 0.45 and citations:
        status = "likely"
    else:
        status = "weak"
        notes.append("Retrieved evidence is weak; answer should be treated as a hypothesis.")

    if blocked:
        notes.append("Forbidden automation language was detected and should be removed.")
    if not citations:
        notes.append("No citations were attached.")

    risk = "low"
    if status in {"weak", "missing_evidence"} or blocked:
        risk = "high"
    elif coverage < 0.5:
        risk = "medium"

    return VerificationResult(
        status=status,
        citation_coverage=coverage,
        hallucination_risk=risk,
        blocked_terms=blocked,
        notes=notes,
    )


def _citation_coverage(answer: str, citations: list[Citation]) -> float:
    if not answer.strip():
        return 0.0
    if not citations:
        return 0.0
    cited_sources = sum(1 for citation in citations if citation.source and citation.title)
    return round(min(cited_sources / max(len(citations), 1), 1.0), 4)
