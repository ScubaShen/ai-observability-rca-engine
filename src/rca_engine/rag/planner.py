from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rca_engine.rag.preprocessor import ProcessedQuery
from rca_engine.rag.query import QueryIntent


SERVICE_ALIASES = {
    "basket": "cart",
    "basketservice": "cart",
    "cartsvc": "cart",
    "cartsrv": "cart",
    "money": "payment",
    "payments": "payment",
}

DOMAIN_EXPANSIONS = {
    "basket": ["cart", "cart storage"],
    "cart": ["basket", "lock contention"],
    "lock": ["contention", "cache saturation"],
    "waiting": ["latency", "queue buildup"],
    "spins": ["latency", "timeout"],
    "release": ["deploy", "config change"],
    "rollout": ["deploy", "config change"],
    "authorizer": ["payment gateway", "dependency latency"],
    "outside": ["external dependency"],
    "502": ["gateway error", "dependency"],
    "手冊": ["runbook"],
    "證據": ["evidence"],
    "根因": ["root cause"],
    "結帳": ["checkout"],
    "購物車": ["cart", "basket"],
    "鎖": ["lock contention"],
    "快取": ["cache saturation", "redis"],
}


DEFAULT_SOURCE_BUDGETS = {
    "exact": 4,
    "current_evidence": 18,
    "keyword": 16,
    "semantic": 16,
    "artifact": 12,
    "runbook": 10,
    "historical": 10,
    "graph": 4,
}


@dataclass(frozen=True)
class RetrievalPlan:
    original_query: str
    keyword_query: str
    semantic_query: str
    intent: QueryIntent
    entities: dict[str, str] = field(default_factory=dict)
    incident_id: str | None = None
    source_budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SOURCE_BUDGETS))
    aliases: dict[str, str] = field(default_factory=dict)

    def trace(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "keyword_query": self.keyword_query,
            "semantic_query": self.semantic_query,
            "intent": self.intent.intent,
            "entities": self.entities,
            "incident_id": self.incident_id,
            "source_budgets": self.source_budgets,
            "aliases": self.aliases,
        }


class RetrievalPlanner:
    def build(
        self,
        processed: ProcessedQuery,
        incident_id: str | None,
        limit: int,
    ) -> RetrievalPlan:
        entities = dict(processed.entities)
        aliases = _aliases(processed.rewritten_query)
        for _, canonical in aliases.items():
            entities.setdefault("service", canonical)

        source_budgets = dict(DEFAULT_SOURCE_BUDGETS)
        source_budgets["current_evidence"] = max(limit * 4, source_budgets["current_evidence"])
        source_budgets["keyword"] = max(limit * 3, source_budgets["keyword"])
        source_budgets["semantic"] = max(limit * 3, source_budgets["semantic"])
        source_budgets["artifact"] = max(limit * 2, source_budgets["artifact"])
        if processed.intent.intent == "runbook":
            source_budgets["runbook"] = max(limit * 3, source_budgets["runbook"])
        if processed.intent.intent == "similar_incident":
            source_budgets["historical"] = max(limit * 3, source_budgets["historical"])

        keyword_query = _keyword_query(processed.rewritten_query, entities, aliases)
        semantic_query = _semantic_query(processed.rewritten_query, aliases)
        return RetrievalPlan(
            original_query=processed.original_query,
            keyword_query=keyword_query,
            semantic_query=semantic_query,
            intent=processed.intent,
            entities=entities,
            incident_id=incident_id or entities.get("incident_id"),
            source_budgets=source_budgets,
            aliases=aliases,
        )


def _aliases(query: str) -> dict[str, str]:
    found: dict[str, str] = {}
    query_tokens = set(_tokens(query))
    for alias, canonical in SERVICE_ALIASES.items():
        if alias in query_tokens:
            found[alias] = canonical
    return found


def _keyword_query(query: str, entities: dict[str, str], aliases: dict[str, str]) -> str:
    additions: list[str] = []
    for value in entities.values():
        if value and value.lower() not in query.lower():
            additions.append(value)
    for canonical in aliases.values():
        if canonical.lower() not in query.lower():
            additions.append(canonical)
    return " ".join([query, *additions]).strip()


def _semantic_query(query: str, aliases: dict[str, str]) -> str:
    additions: list[str] = []
    tokens = set(_tokens(query))
    for alias, canonical in aliases.items():
        additions.extend([alias, canonical])
    for token, expansions in DOMAIN_EXPANSIONS.items():
        if token in tokens or token in query:
            additions.extend(expansions)
    deduped = []
    seen: set[str] = set()
    for addition in additions:
        lowered = addition.lower()
        if lowered in seen or lowered in query.lower():
            continue
        seen.add(lowered)
        deduped.append(addition)
    return " ".join([query, *deduped]).strip()


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_.-]+", value.lower()) if len(token) > 1]
