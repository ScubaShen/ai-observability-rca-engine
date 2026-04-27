from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    kafka_group_id: str = os.getenv("KAFKA_GROUP_ID", "ai-observability-rca-engine")
    input_topics: tuple[str, ...] = tuple(
        _csv_env(
            "RCA_INPUT_TOPICS",
            "observability.logs,observability.metrics,observability.traces",
        )
    )
    output_topic_metric_anomaly: str = os.getenv("RCA_TOPIC_METRIC_ANOMALY", "metric.anomaly")
    output_topic_log_error_pattern: str = os.getenv(
        "RCA_TOPIC_LOG_ERROR_PATTERN", "log.error_pattern"
    )
    output_topic_trace_slow_span: str = os.getenv("RCA_TOPIC_TRACE_SLOW_SPAN", "trace.slow_span")
    output_topic_trace_error: str = os.getenv("RCA_TOPIC_TRACE_ERROR", "trace.error")
    output_topic_incident_candidate: str = os.getenv(
        "RCA_TOPIC_INCIDENT_CANDIDATE", "incident.candidate"
    )
    output_topic_incident_evidence: str = os.getenv("RCA_TOPIC_INCIDENT_EVIDENCE", "incident.evidence")
    output_topic_rca_result: str = os.getenv("RCA_TOPIC_RESULT", "rca.result")
    output_topic_agent_report: str = os.getenv("RCA_TOPIC_AGENT_REPORT", "rca.agent_report")
    dead_letter_topic: str = os.getenv("RCA_TOPIC_DEAD_LETTER", "rca.dead_letter")
    runtime_dir: Path = Path(os.getenv("RCA_RUNTIME_DIR", "runtime"))
    slow_span_threshold_ms: float = float(os.getenv("RCA_SLOW_SPAN_THRESHOLD_MS", "1000"))
    metric_min_samples: int = int(os.getenv("RCA_METRIC_MIN_SAMPLES", "5"))
    metric_stddev_multiplier: float = float(os.getenv("RCA_METRIC_STDDEV_MULTIPLIER", "3"))
    incident_window_seconds: int = int(os.getenv("RCA_INCIDENT_WINDOW_SECONDS", "300"))
    api_host: str = os.getenv("RCA_API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("RCA_API_PORT", "8000"))
    postgres_dsn: str = os.getenv("POSTGRES_DSN", "")
    neo4j_uri: str = os.getenv("NEO4J_URI", "")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "")
    rag_embedding_dimensions: int = int(os.getenv("RAG_EMBEDDING_DIMENSIONS", "1536"))
    rag_cache_ttl_seconds: int = int(os.getenv("RAG_CACHE_TTL_SECONDS", "300"))
    llm_enabled: bool = os.getenv("RAG_LLM_ENABLED", "false").lower() == "true"
    llm_api_url: str = os.getenv("RAG_LLM_API_URL", "")
    llm_api_key: str = os.getenv("RAG_LLM_API_KEY", "")
    llm_model: str = os.getenv("RAG_LLM_MODEL", "")
    llm_timeout_seconds: float = float(os.getenv("RAG_LLM_TIMEOUT_SECONDS", "20"))

    @property
    def output_dir(self) -> Path:
        return self.runtime_dir / "output"


def load_settings() -> Settings:
    return Settings()
