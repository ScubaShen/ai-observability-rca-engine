from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rca_engine.correlator import IncidentCandidateCorrelator
from rca_engine.evaluation.replay_store import ReplayStore
from rca_engine.evaluation.schemas import ReplaySummary
from rca_engine.models import NormalizedEvent, RCAResult
from rca_engine.processors.logs import extract_log_error_patterns
from rca_engine.processors.metrics import MetricAnomalyDetector
from rca_engine.processors.traces import extract_trace_events
from rca_engine.rag.indexer import RAGIndexer
from rca_engine.rca.orchestrator import RCAOrchestrator


HIGH_VALUE_EVENT_TYPES = {
    "log.error_pattern",
    "metric.anomaly",
    "trace.slow_span",
    "trace.error",
    "deploy.change",
    "config.change",
}


class ReplayResult:
    def __init__(self, store: ReplayStore, summary: ReplaySummary) -> None:
        self.store = store
        self.summary = summary


def run_replay(
    *,
    events_path: Path,
    runbooks_path: Path,
    incident_window_seconds: int = 300,
    metric_min_samples: int = 5,
    metric_stddev_multiplier: float = 3.0,
    slow_span_threshold_ms: float = 1000.0,
) -> ReplayResult:
    store = ReplayStore(runbooks=_load_json(runbooks_path))
    correlator = IncidentCandidateCorrelator(window_seconds=incident_window_seconds)
    metric_detector = MetricAnomalyDetector(
        min_samples=metric_min_samples,
        stddev_multiplier=metric_stddev_multiplier,
    )
    rca_orchestrator = RCAOrchestrator(store)
    indexer = RAGIndexer(store)
    indexer.index_runbooks()

    input_events = [NormalizedEvent.model_validate(row) for row in _load_json(events_path)]
    extracted_count = 0
    analyzed_incidents: set[str] = set()

    for source_event in input_events:
        for event in _extract_events(
            source_event,
            metric_detector=metric_detector,
            slow_span_threshold_ms=slow_span_threshold_ms,
        ):
            extracted_count += 1
            store.save_event(event)
            candidate = correlator.process(event)
            if not candidate:
                continue
            store.save_candidate(candidate)
            result = rca_orchestrator.analyze(candidate)
            store.save_rca_result(result)
            indexer.index_rca_result(result)
            analyzed_incidents.add(result.incident_id)

    summary = ReplaySummary(
        input_event_count=len(input_events),
        extracted_event_count=extracted_count,
        candidate_count=len(store.candidates),
        rca_result_count=len(store.rca_results),
        rag_document_count=len(store.rag_documents),
        incident_ids=sorted(analyzed_incidents),
    )
    return ReplayResult(store=store, summary=summary)


def _extract_events(
    event: NormalizedEvent,
    *,
    metric_detector: MetricAnomalyDetector,
    slow_span_threshold_ms: float,
) -> list[NormalizedEvent]:
    if event.event_type == "log.raw":
        return extract_log_error_patterns(event)
    if event.event_type == "metric.raw":
        return metric_detector.process(event)
    if event.event_type == "trace.raw":
        return extract_trace_events(event, slow_threshold_ms=slow_span_threshold_ms)
    if event.event_type in HIGH_VALUE_EVENT_TYPES:
        return [event]
    return []


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("items", []))
    return []
