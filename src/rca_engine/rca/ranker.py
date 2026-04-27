from __future__ import annotations

from rca_engine.models import RootCauseHypothesis


class RootCauseRanker:
    def rank(self, hypotheses: list[RootCauseHypothesis]) -> list[RootCauseHypothesis]:
        ranked = sorted(
            hypotheses,
            key=lambda item: (item.confidence, len(item.supporting_event_ids)),
            reverse=True,
        )
        return ranked[:5]
