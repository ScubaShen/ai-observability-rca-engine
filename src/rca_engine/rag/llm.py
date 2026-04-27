from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from rca_engine.models import KnowledgeMatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMSettings:
    api_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 20.0
    enabled: bool = False


class OpenAICompatibleLLM:
    """Small OpenAI-compatible chat client with deterministic fallback outside the class."""

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def available(self) -> bool:
        return bool(self.settings.enabled and self.settings.api_url and self.settings.model)

    def complete(self, *, question: str, context: list[KnowledgeMatch]) -> str | None:
        if not self.available():
            return None
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an RCA copilot. Answer only from the supplied evidence. "
                        "If evidence is insufficient, say what is missing. "
                        "Do not propose automatic rollback, restart, scale, ticket execution, or any executor workflow."
                    ),
                },
                {
                    "role": "user",
                    "content": _prompt(question, context),
                },
            ],
            "temperature": 0.2,
        }
        try:
            response = requests.post(
                self.settings.api_url,
                headers=headers,
                json=payload,
                timeout=self.settings.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            message = choices[0].get("message") or {}
            content = message.get("content")
            return str(content).strip() if content else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM completion failed; falling back to deterministic answer: %s", exc)
            return None


def _prompt(question: str, context: list[KnowledgeMatch]) -> str:
    lines = [
        f"Question: {question}",
        "",
        "Evidence context:",
    ]
    for index, match in enumerate(context, start=1):
        lines.extend(
            [
                f"[{index}] source={match.source} ref_id={match.ref_id} title={match.title} score={match.score}",
                match.content[:1800],
                "",
            ]
        )
    lines.extend(
        [
            "Answer format:",
            "- Direct answer",
            "- Supporting evidence with source numbers",
            "- Manual runbook or follow-up questions if useful",
            "- Missing evidence if confidence is weak",
        ]
    )
    return "\n".join(lines)
