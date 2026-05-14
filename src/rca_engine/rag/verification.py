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
    claim_notes = claim_guardrail_notes(answer, citations)
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
    notes.extend(claim_notes)

    risk = "low"
    if status in {"weak", "missing_evidence"} or blocked or claim_notes:
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


def apply_claim_guardrail(answer: str, citations: list[Citation]) -> tuple[str, list[str]]:
    notes = claim_guardrail_notes(answer, citations)
    if not notes:
        return answer, []
    evidence_ids = _citation_evidence_ids(citations)
    if not evidence_ids:
        return answer, notes
    appendix = (
        "\n\nEvidence guardrail: Treat any diagnosis or repair step without one of these "
        f"evidence IDs as a hypothesis, not a confirmed conclusion: {', '.join(evidence_ids[:10])}."
    )
    if "Evidence guardrail:" in answer:
        return answer, notes
    return f"{answer}{appendix}", notes


def claim_guardrail_notes(answer: str, citations: list[Citation]) -> list[str]:
    evidence_ids = _citation_evidence_ids(citations)
    if not evidence_ids:
        return ["No evidence IDs were available for claim-level grounding."]
    lowered = answer.lower()
    if not any(evidence_id.lower() in lowered for evidence_id in evidence_ids):
        return ["No cited evidence IDs were mentioned in the generated answer."]
    return []


def _citation_coverage(answer: str, citations: list[Citation]) -> float:
    if not answer.strip():
        return 0.0
    if not citations:
        return 0.0
    cited_sources = sum(1 for citation in citations if citation.source and citation.title)
    return round(min(cited_sources / max(len(citations), 1), 1.0), 4)


def _citation_evidence_ids(citations: list[Citation]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for citation in citations:
        for evidence_id in citation.evidence_ids:
            value = str(evidence_id).strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
    return ids
