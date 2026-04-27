from __future__ import annotations

from rca_engine.hash_utils import stable_id
from rca_engine.models import CausalLink, NormalizedEvent, ServiceDependencyInsight


class CausalGraphBuilder:
    def build(
        self,
        events: list[NormalizedEvent],
        dependency_insights: list[ServiceDependencyInsight],
    ) -> list[CausalLink]:
        links: list[CausalLink] = []
        links.extend(_time_order_links(events))
        links.extend(_same_trace_links(events))
        links.extend(_dependency_links(dependency_insights))
        return _dedupe_links(links)


def _time_order_links(events: list[NormalizedEvent]) -> list[CausalLink]:
    links: list[CausalLink] = []
    for left, right in zip(events, events[1:]):
        if left.event_id == right.event_id:
            continue
        links.append(
            CausalLink(
                source_id=left.event_id,
                target_id=right.event_id,
                relation="triggered_before",
                confidence=0.45,
                reason="Evidence occurred earlier in the incident timeline.",
            )
        )
    return links


def _same_trace_links(events: list[NormalizedEvent]) -> list[CausalLink]:
    links: list[CausalLink] = []
    for index, left in enumerate(events):
        if not left.trace_id:
            continue
        for right in events[index + 1 :]:
            if left.trace_id == right.trace_id and left.event_id != right.event_id:
                links.append(
                    CausalLink(
                        source_id=left.event_id,
                        target_id=right.event_id,
                        relation="same_trace",
                        confidence=0.72,
                        reason="Events share the same trace id.",
                    )
                )
    return links


def _dependency_links(dependency_insights: list[ServiceDependencyInsight]) -> list[CausalLink]:
    links: list[CausalLink] = []
    for insight in dependency_insights:
        if not insight.is_suspect:
            continue
        for event_id in insight.evidence_event_ids:
            links.append(
                CausalLink(
                    source_id=f"dependency:{insight.target}",
                    target_id=event_id,
                    relation="possible_cause_of",
                    confidence=0.66,
                    reason=f"Suspect dependency signal observed for {insight.target}.",
                )
            )
    return links


def _dedupe_links(links: list[CausalLink]) -> list[CausalLink]:
    deduped: dict[str, CausalLink] = {}
    for link in links:
        key = stable_id(
            "link",
            {
                "source_id": link.source_id,
                "target_id": link.target_id,
                "relation": link.relation,
            },
        )
        deduped[key] = link.model_copy(update={"link_id": key})
    return list(deduped.values())
