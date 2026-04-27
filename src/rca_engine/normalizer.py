from __future__ import annotations

import json
from typing import Any

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

from rca_engine.hash_utils import stable_id
from rca_engine.models import EvidenceRef, NormalizedEvent, Severity
from rca_engine.timeutils import now_utc_iso, unix_nano_to_iso


class NormalizationError(ValueError):
    pass


def normalize_kafka_payload(source_topic: str, payload: bytes) -> list[NormalizedEvent]:
    json_events = _try_json_payload(source_topic, payload)
    if json_events is not None:
        return json_events

    if source_topic.endswith(".logs"):
        return _normalize_logs(source_topic, payload)
    if source_topic.endswith(".metrics"):
        return _normalize_metrics(source_topic, payload)
    if source_topic.endswith(".traces"):
        return _normalize_traces(source_topic, payload)
    raise NormalizationError(f"Unsupported source topic: {source_topic}")


def _try_json_payload(source_topic: str, payload: bytes) -> list[NormalizedEvent] | None:
    stripped = payload.lstrip()
    if not stripped.startswith((b"{", b"[")):
        return None
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"Invalid JSON payload: {exc}") from exc

    items = decoded if isinstance(decoded, list) else [decoded]
    events: list[NormalizedEvent] = []
    for item in items:
        if not isinstance(item, dict):
            raise NormalizationError("JSON payload items must be objects")
        event_time = str(item.get("event_time") or item.get("timestamp") or now_utc_iso())
        event_type = str(item.get("event_type") or _raw_event_type(source_topic))
        service = str(item.get("service") or "unknown")
        summary = str(item.get("summary") or item.get("message") or event_type)
        events.append(
            NormalizedEvent(
                event_id=str(
                    item.get("event_id")
                    or stable_id(
                        "event",
                        {
                            "source_topic": source_topic,
                            "event_type": event_type,
                            "event_time": event_time,
                            "service": service,
                            "summary": summary,
                        },
                    )
                ),
                event_type=event_type,
                source_topic=source_topic,
                event_time=event_time,
                ingest_time=str(item.get("ingest_time") or now_utc_iso()),
                service=service,
                env=str(item.get("env") or "unknown"),
                severity=_normalize_severity(item.get("severity")),
                trace_id=item.get("trace_id"),
                span_id=item.get("span_id"),
                correlation_keys=list(item.get("correlation_keys") or _correlation_keys(service, None, None)),
                summary=summary,
                attributes=dict(item.get("attributes") or {}),
                evidence_refs=[EvidenceRef(**ref) for ref in item.get("evidence_refs", [])],
            )
        )
    return events


def _normalize_logs(source_topic: str, payload: bytes) -> list[NormalizedEvent]:
    request = ExportLogsServiceRequest()
    try:
        request.ParseFromString(payload)
    except DecodeError as exc:
        raise NormalizationError(f"Failed to decode OTLP logs protobuf: {exc}") from exc

    events: list[NormalizedEvent] = []
    for resource_logs in request.resource_logs:
        resource_attrs = _attributes_to_dict(resource_logs.resource.attributes)
        for scope_logs in resource_logs.scope_logs:
            scope_attrs = _attributes_to_dict(scope_logs.scope.attributes)
            for record in scope_logs.log_records:
                attrs = {**resource_attrs, **scope_attrs, **_attributes_to_dict(record.attributes)}
                service = _service_name(attrs)
                env = _env_name(attrs)
                message = _any_value_to_python(record.body)
                if message is None:
                    message = attrs.get("message") or ""
                event_time = unix_nano_to_iso(record.time_unix_nano) or unix_nano_to_iso(
                    record.observed_time_unix_nano
                ) or now_utc_iso()
                trace_id = _bytes_to_hex(record.trace_id)
                span_id = _bytes_to_hex(record.span_id)
                severity = _log_severity(record.severity_text, record.severity_number)
                summary = str(message)[:500] or "Log record"
                attrs["message"] = str(message)
                events.append(
                    NormalizedEvent(
                        event_id=stable_id(
                            "log",
                            {
                                "source_topic": source_topic,
                                "event_time": event_time,
                                "service": service,
                                "trace_id": trace_id,
                                "span_id": span_id,
                                "message": summary,
                            },
                        ),
                        event_type="log.raw",
                        source_topic=source_topic,
                        event_time=event_time,
                        service=service,
                        env=env,
                        severity=severity,
                        trace_id=trace_id,
                        span_id=span_id,
                        correlation_keys=_correlation_keys(service, trace_id, span_id),
                        summary=summary,
                        attributes=attrs,
                        evidence_refs=[
                            EvidenceRef(
                                source="loki",
                                ref_type="log_query",
                                query=f'{{service="{service}"}}',
                                attributes={"source_topic": source_topic},
                            )
                        ],
                    )
                )
    return events


def _normalize_metrics(source_topic: str, payload: bytes) -> list[NormalizedEvent]:
    request = ExportMetricsServiceRequest()
    try:
        request.ParseFromString(payload)
    except DecodeError as exc:
        raise NormalizationError(f"Failed to decode OTLP metrics protobuf: {exc}") from exc

    events: list[NormalizedEvent] = []
    for resource_metrics in request.resource_metrics:
        resource_attrs = _attributes_to_dict(resource_metrics.resource.attributes)
        service = _service_name(resource_attrs)
        env = _env_name(resource_attrs)
        for scope_metrics in resource_metrics.scope_metrics:
            scope_attrs = _attributes_to_dict(scope_metrics.scope.attributes)
            for metric in scope_metrics.metrics:
                for point, value in _metric_points(metric):
                    attrs = {
                        **resource_attrs,
                        **scope_attrs,
                        **_attributes_to_dict(point.attributes),
                        "metric_name": metric.name,
                        "metric_description": metric.description,
                        "metric_unit": metric.unit,
                        "value": value,
                    }
                    event_time = unix_nano_to_iso(point.time_unix_nano) or now_utc_iso()
                    events.append(
                        NormalizedEvent(
                            event_id=stable_id(
                                "metric",
                                {
                                    "source_topic": source_topic,
                                    "event_time": event_time,
                                    "service": service,
                                    "metric_name": metric.name,
                                    "value": value,
                                },
                            ),
                            event_type="metric.raw",
                            source_topic=source_topic,
                            event_time=event_time,
                            service=service,
                            env=env,
                            severity="info",
                            correlation_keys=_correlation_keys(service, None, None)
                            + [f"metric:{metric.name}"],
                            summary=f"Metric sample {metric.name}={value}",
                            attributes=attrs,
                            evidence_refs=[
                                EvidenceRef(
                                    source="prometheus",
                                    ref_type="promql",
                                    query=metric.name,
                                    attributes={"source_topic": source_topic},
                                )
                            ],
                        )
                    )
    return events


def _normalize_traces(source_topic: str, payload: bytes) -> list[NormalizedEvent]:
    request = ExportTraceServiceRequest()
    try:
        request.ParseFromString(payload)
    except DecodeError as exc:
        raise NormalizationError(f"Failed to decode OTLP traces protobuf: {exc}") from exc

    events: list[NormalizedEvent] = []
    for resource_spans in request.resource_spans:
        resource_attrs = _attributes_to_dict(resource_spans.resource.attributes)
        service = _service_name(resource_attrs)
        env = _env_name(resource_attrs)
        for scope_spans in resource_spans.scope_spans:
            scope_attrs = _attributes_to_dict(scope_spans.scope.attributes)
            for span in scope_spans.spans:
                trace_id = _bytes_to_hex(span.trace_id)
                span_id = _bytes_to_hex(span.span_id)
                event_time = unix_nano_to_iso(span.start_time_unix_nano) or now_utc_iso()
                duration_ms = None
                if span.start_time_unix_nano and span.end_time_unix_nano:
                    duration_ms = (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000
                status_code = _status_code_name(span.status.code)
                attrs = {
                    **resource_attrs,
                    **scope_attrs,
                    **_attributes_to_dict(span.attributes),
                    "span_name": span.name,
                    "span_kind": span.kind,
                    "duration_ms": duration_ms,
                    "status_code": status_code,
                }
                severity: Severity = "error" if status_code == "ERROR" else "info"
                events.append(
                    NormalizedEvent(
                        event_id=stable_id(
                            "trace",
                            {
                                "source_topic": source_topic,
                                "event_time": event_time,
                                "service": service,
                                "trace_id": trace_id,
                                "span_id": span_id,
                                "span_name": span.name,
                            },
                        ),
                        event_type="trace.raw",
                        source_topic=source_topic,
                        event_time=event_time,
                        service=service,
                        env=env,
                        severity=severity,
                        trace_id=trace_id,
                        span_id=span_id,
                        correlation_keys=_correlation_keys(service, trace_id, span_id),
                        summary=f"Span {span.name}",
                        attributes=attrs,
                        evidence_refs=[
                            EvidenceRef(
                                source="tempo",
                                ref_type="trace_id",
                                ref_id=trace_id,
                                attributes={"source_topic": source_topic},
                            )
                        ],
                    )
                )
    return events


def _metric_points(metric: Any) -> list[tuple[Any, float]]:
    data = metric.WhichOneof("data")
    if data == "gauge":
        return [(point, _number_data_point_value(point)) for point in metric.gauge.data_points]
    if data == "sum":
        return [(point, _number_data_point_value(point)) for point in metric.sum.data_points]
    if data == "histogram":
        return [(point, float(point.sum)) for point in metric.histogram.data_points]
    return []


def _number_data_point_value(point: Any) -> float:
    value_kind = point.WhichOneof("value")
    if value_kind == "as_double":
        return float(point.as_double)
    if value_kind == "as_int":
        return float(point.as_int)
    return 0.0


def _attributes_to_dict(attributes: Any) -> dict[str, Any]:
    return {item.key: _any_value_to_python(item.value) for item in attributes}


def _any_value_to_python(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "bytes_value":
        return value.bytes_value.hex()
    if kind == "array_value":
        return [_any_value_to_python(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes_to_dict(value.kvlist_value.values)
    return str(value)


def _service_name(attributes: dict[str, Any]) -> str:
    return str(attributes.get("service.name") or attributes.get("service") or "unknown")


def _env_name(attributes: dict[str, Any]) -> str:
    return str(
        attributes.get("deployment.environment")
        or attributes.get("deployment.environment.name")
        or attributes.get("env")
        or "unknown"
    )


def _bytes_to_hex(value: bytes) -> str | None:
    return value.hex() if value else None


def _log_severity(severity_text: str, severity_number: int) -> Severity:
    if severity_text:
        return _normalize_severity(severity_text)
    if severity_number >= 21:
        return "critical"
    if severity_number >= 17:
        return "error"
    if severity_number >= 13:
        return "warning"
    if severity_number >= 5:
        return "debug"
    return "info"


def _normalize_severity(value: object) -> Severity:
    text = str(value or "info").lower()
    if "fatal" in text or "critical" in text:
        return "critical"
    if "error" in text or text == "err":
        return "error"
    if "warn" in text:
        return "warning"
    if "debug" in text or "trace" in text:
        return "debug"
    return "info"


def _status_code_name(code: int) -> str:
    if code == 2:
        return "ERROR"
    if code == 1:
        return "OK"
    if code == 0:
        return "UNSET"
    return str(code)


def _correlation_keys(service: str, trace_id: str | None, span_id: str | None) -> list[str]:
    keys = [f"service:{service}"]
    if trace_id:
        keys.append(f"trace:{trace_id}")
    if span_id:
        keys.append(f"span:{span_id}")
    return keys


def _raw_event_type(source_topic: str) -> str:
    if source_topic.endswith(".logs"):
        return "log.raw"
    if source_topic.endswith(".metrics"):
        return "metric.raw"
    if source_topic.endswith(".traces"):
        return "trace.raw"
    return "event.raw"
