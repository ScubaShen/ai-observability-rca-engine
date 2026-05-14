from __future__ import annotations

from rca_engine.models import InvestigationState


def merge_investigation_state(
    current: InvestigationState,
    update: InvestigationState,
) -> InvestigationState:
    return current.model_copy(
        update={
            "incident_id": update.incident_id or current.incident_id,
            "confirmed_facts": _dedupe(
                [*current.confirmed_facts, *update.confirmed_facts]
            ),
            "active_hypotheses": _dedupe(
                [
                    item
                    for item in [*current.active_hypotheses, *update.active_hypotheses]
                    if item not in set(update.excluded_hypotheses)
                ]
            ),
            "excluded_hypotheses": _dedupe(
                [*current.excluded_hypotheses, *update.excluded_hypotheses]
            ),
            "selected_evidence_ids": _dedupe(
                [*current.selected_evidence_ids, *update.selected_evidence_ids]
            ),
            "open_questions": _dedupe([*current.open_questions, *update.open_questions]),
            "updated_at": update.updated_at,
        }
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped
