from __future__ import annotations

import json
import logging
from typing import Any

from kafka import KafkaConsumer, KafkaProducer

from rca_engine.config import Settings
from rca_engine.correlator import IncidentCandidateCorrelator
from rca_engine.hash_utils import stable_id
from rca_engine.agents.orchestrator import RCAAgentOrchestrator
from rca_engine.models import (
    DeadLetterEvent,
    IncidentCandidate,
    NormalizedEvent,
    RCAAgentReport,
    RCAResult,
)
from rca_engine.normalizer import NormalizationError, normalize_kafka_payload
from rca_engine.processors.logs import extract_log_error_patterns
from rca_engine.processors.metrics import MetricAnomalyDetector
from rca_engine.processors.traces import extract_trace_events
from rca_engine.rag.embedding import HashEmbeddingProvider
from rca_engine.rag.indexer import RAGIndexer
from rca_engine.rca.orchestrator import RCAOrchestrator
from rca_engine.storage.factory import build_storage

logger = logging.getLogger(__name__)


class KafkaRCAWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = build_storage(settings)
        self.metric_detector = MetricAnomalyDetector(
            min_samples=settings.metric_min_samples,
            stddev_multiplier=settings.metric_stddev_multiplier,
        )
        self.correlator = IncidentCandidateCorrelator(
            window_seconds=settings.incident_window_seconds
        )
        self.rca_orchestrator = RCAOrchestrator(self.store)
        self.agent_orchestrator = RCAAgentOrchestrator()
        self.rag_indexer = RAGIndexer(
            self.store,
            embedding_provider=HashEmbeddingProvider(dimensions=settings.rag_embedding_dimensions),
        )
        self.rag_indexer.index_runbooks()
        self.consumer = KafkaConsumer(
            *settings.input_topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda value: value,
        )
        self.producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda value: json.dumps(
                value, ensure_ascii=False, sort_keys=True
            ).encode("utf-8"),
        )

    def run_forever(self) -> None:
        logger.info("Starting RCA Kafka worker for topics: %s", ", ".join(self.settings.input_topics))
        for record in self.consumer:
            self.process_record(record.topic, record.value, record_metadata=record)

    def process_record(self, source_topic: str, payload: bytes, record_metadata: Any | None = None) -> None:
        # A single worker owns the ingestion-to-analysis chain so each input
        # record produces a predictable sequence of derived artifacts: normalized
        # events, incident candidates, RCA results, operator reports, and
        # retrieval documents. This keeps the initial implementation easy to
        # reason about, at the cost of throughput-oriented decoupling.
        try:
            raw_events = normalize_kafka_payload(source_topic, payload)
        except NormalizationError as exc:
            self._handle_dead_letter(source_topic, payload, str(exc), record_metadata)
            return

        for raw_event in raw_events:
            for event in self._extract_high_value_events(raw_event):
                self._publish_event(event)
                self.store.save_event(event)
                candidate = self.correlator.process(event)
                if candidate is not None:
                    self._publish_candidate(candidate)
                    self.store.save_candidate(candidate)
                    rca_result = self.rca_orchestrator.analyze(candidate)
                    self._publish_rca_result(rca_result)
                    self.store.save_rca_result(rca_result)
                    self.rag_indexer.index_rca_result(rca_result)
                    agent_report = self.agent_orchestrator.analyze(rca_result)
                    self._publish_agent_report(agent_report)
                    self.store.save_agent_report(agent_report)
                    self.rag_indexer.index_agent_report(agent_report)
        self.producer.flush()

    def _extract_high_value_events(self, event: NormalizedEvent) -> list[NormalizedEvent]:
        if event.event_type == "log.raw":
            return extract_log_error_patterns(event)
        if event.event_type == "metric.raw":
            return self.metric_detector.process(event)
        if event.event_type == "trace.raw":
            return extract_trace_events(
                event,
                slow_threshold_ms=self.settings.slow_span_threshold_ms,
            )
        return []

    def _publish_event(self, event: NormalizedEvent) -> None:
        topic = self._topic_for_event(event)
        payload = event.model_dump(mode="json")
        self.producer.send(topic, payload)
        self.producer.send(self.settings.output_topic_incident_evidence, payload)

    def _publish_candidate(self, candidate: IncidentCandidate) -> None:
        self.producer.send(
            self.settings.output_topic_incident_candidate,
            candidate.model_dump(mode="json"),
        )

    def _publish_rca_result(self, result: RCAResult) -> None:
        self.producer.send(
            self.settings.output_topic_rca_result,
            result.model_dump(mode="json"),
        )

    def _publish_agent_report(self, report: RCAAgentReport) -> None:
        self.producer.send(
            self.settings.output_topic_agent_report,
            report.model_dump(mode="json"),
        )

    def _handle_dead_letter(
        self,
        source_topic: str,
        payload: bytes,
        reason: str,
        record_metadata: Any | None,
    ) -> None:
        # Dead-letter writes preserve enough broker metadata for later replay or
        # triage without forcing the worker to keep malformed payloads in memory.
        attributes: dict[str, Any] = {}
        if record_metadata is not None:
            attributes = {
                "partition": getattr(record_metadata, "partition", None),
                "offset": getattr(record_metadata, "offset", None),
                "timestamp": getattr(record_metadata, "timestamp", None),
            }
        dead_letter = DeadLetterEvent(
            event_id=stable_id(
                "dead_letter",
                {
                    "source_topic": source_topic,
                    "payload_size_bytes": len(payload),
                    "reason": reason,
                    **attributes,
                },
            ),
            source_topic=source_topic,
            reason=reason,
            payload_size_bytes=len(payload),
            attributes=attributes,
        )
        logger.warning("Dead-letter event from %s: %s", source_topic, reason)
        self.store.jsonl.append("dead-letter.jsonl", dead_letter)
        self.producer.send(
            self.settings.dead_letter_topic,
            dead_letter.model_dump(mode="json"),
        )
        self.producer.flush()

    def _topic_for_event(self, event: NormalizedEvent) -> str:
        if event.event_type == "metric.anomaly":
            return self.settings.output_topic_metric_anomaly
        if event.event_type == "log.error_pattern":
            return self.settings.output_topic_log_error_pattern
        if event.event_type == "trace.slow_span":
            return self.settings.output_topic_trace_slow_span
        if event.event_type == "trace.error":
            return self.settings.output_topic_trace_error
        return self.settings.output_topic_incident_evidence
