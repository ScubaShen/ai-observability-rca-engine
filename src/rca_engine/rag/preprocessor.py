from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rca_engine.rag.query import QueryIntent, understand_query


ENTITY_PATTERNS = {
    "incident_id": re.compile(r"\bincident[_-][a-zA-Z0-9_.-]+\b"),
    "trace_id": re.compile(r"\btrace[_-][a-zA-Z0-9_.-]+\b"),
    "error_code": re.compile(r"\b(?:HTTP\s*)?[45][0-9]{2}\b|\b[A-Z][A-Za-z0-9_]*Exception\b"),
    "deploy_id": re.compile(r"\b(?:deploy|release|rollout)[_-][a-zA-Z0-9_.-]+\b"),
    "version": re.compile(r"\bv?\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9_.-]+)?\b"),
    "endpoint": re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+(/[a-zA-Z0-9_./{}:-]+)\b|(/[a-zA-Z0-9_./{}:-]+)"),
    "metric_name": re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_.]*(?:latency|duration|error|cpu|memory|gc|queue|saturation)[a-zA-Z0-9_.]*\b"),
    "time_range": re.compile(r"\b(?:last|past)\s+\d+\s*(?:m|min|minute|h|hour|d|day)s?\b"),
    "dependency": re.compile(r"\b(?:downstream|upstream|dependency|redis|postgres|kafka|mysql|payment|checkout|cart)\b"),
}


@dataclass(frozen=True)
class ProcessedQuery:
    original_query: str
    rewritten_query: str
    intent: QueryIntent
    entities: dict[str, str] = field(default_factory=dict)
    rewrite_applied: bool = False
    drift_detected: bool = False
    notes: list[str] = field(default_factory=list)

    def trace(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "intent": self.intent.intent,
            "entities": self.entities,
            "rewrite_applied": self.rewrite_applied,
            "drift_detected": self.drift_detected,
            "notes": self.notes,
        }


class EntityExtractor:
    def extract(self, query: str, intent: QueryIntent) -> dict[str, str]:
        entities: dict[str, str] = {}
        lowered = query.lower()
        if intent.service:
            entities["service"] = intent.service
        if intent.env:
            entities["env"] = intent.env

        for name, pattern in ENTITY_PATTERNS.items():
            match = pattern.search(query)
            if match:
                value = match.group(0).strip()
                if name not in {"endpoint", "time_range"}:
                    value = value.replace(" ", "")
                entities[name] = value

        for name in (
            "incident_id",
            "service",
            "env",
            "trace_id",
            "span_id",
            "error_code",
            "metric_name",
            "endpoint",
            "dependency",
            "deploy_id",
            "version",
        ):
            match = re.search(rf"\b{name}\s*[:=]\s*([a-zA-Z0-9_./{{}}:-]+)", lowered)
            if match:
                entities[name] = match.group(1)
        return entities


class BoundedQueryRewriter:
    def rewrite(self, query: str, intent: QueryIntent, entities: dict[str, str]) -> tuple[str, bool]:
        additions: list[str] = []
        for key in (
            "incident_id",
            "service",
            "env",
            "trace_id",
            "span_id",
            "error_code",
            "metric_name",
            "endpoint",
            "dependency",
            "deploy_id",
            "version",
            "time_range",
        ):
            value = entities.get(key)
            if value and value.lower() not in query.lower():
                additions.append(f"{key}:{value}" if key not in {"incident_id", "trace_id"} else value)
        if intent.intent != "general" and intent.intent not in query.lower():
            additions.append(intent.intent)
        if not additions:
            return query, False
        return " ".join([query, *additions]), True


class DriftChecker:
    def has_drift(self, original_query: str, rewritten_query: str, entities: dict[str, str]) -> bool:
        rewritten_lower = rewritten_query.lower()
        for value in entities.values():
            if value and value.lower() not in rewritten_lower:
                return True
        original_tokens = set(_tokens(original_query))
        rewritten_tokens = set(_tokens(rewritten_query))
        if not original_tokens:
            return False
        retained = len(original_tokens.intersection(rewritten_tokens)) / len(original_tokens)
        return retained < 0.8


class QueryPreprocessor:
    def __init__(
        self,
        entity_extractor: EntityExtractor | None = None,
        rewriter: BoundedQueryRewriter | None = None,
        drift_checker: DriftChecker | None = None,
    ) -> None:
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.rewriter = rewriter or BoundedQueryRewriter()
        self.drift_checker = drift_checker or DriftChecker()

    def process(self, query: str) -> ProcessedQuery:
        intent = understand_query(query)
        entities = self.entity_extractor.extract(query, intent)
        rewritten, rewrite_applied = self.rewriter.rewrite(query, intent, entities)
        drift_detected = self.drift_checker.has_drift(query, rewritten, entities)
        notes: list[str] = []
        if drift_detected:
            notes.append("Bounded rewrite drift detected; original query was used.")
            rewritten = query
            rewrite_applied = False
        return ProcessedQuery(
            original_query=query,
            rewritten_query=rewritten,
            intent=intent,
            entities=entities,
            rewrite_applied=rewrite_applied,
            drift_detected=drift_detected,
            notes=notes,
        )


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_.-]+", value.lower()) if len(token) > 1]
