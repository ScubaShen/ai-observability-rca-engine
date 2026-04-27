from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryIntent:
    intent: str
    service: str | None = None
    env: str | None = None
    needs_llm: bool = False
    keywords: list[str] = field(default_factory=list)


INTENT_KEYWORDS = {
    "postmortem": ["postmortem", "report", "draft", "summary"],
    "root_cause": ["root cause", "why", "原因", "根因", "rca"],
    "evidence": ["evidence", "support", "proof", "timeline", "證據"],
    "runbook": ["runbook", "steps", "manual", "排查", "手冊"],
    "similar_incident": ["similar", "history", "historical", "相似", "歷史"],
}


def understand_query(question: str) -> QueryIntent:
    lowered = question.lower()
    intent = "general"
    for candidate, phrases in INTENT_KEYWORDS.items():
        if any(phrase in lowered for phrase in phrases):
            intent = candidate
            break

    service = _extract_named_value(lowered, "service")
    env = _extract_named_value(lowered, "env")
    needs_llm = intent in {"postmortem", "root_cause", "similar_incident"} or len(question) > 180
    return QueryIntent(
        intent=intent,
        service=service,
        env=env,
        needs_llm=needs_llm,
        keywords=_tokens(question),
    )


def _extract_named_value(text: str, name: str) -> str | None:
    match = re.search(rf"{name}\s*[:=]\s*([a-zA-Z0-9_.-]+)", text)
    return match.group(1) if match else None


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_.-]+", text.lower()) if len(token) > 1]
