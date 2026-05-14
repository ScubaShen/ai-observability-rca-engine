from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

import requests

from rca_engine.models import KnowledgeMatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "disabled"
    api_url: str = ""
    api_key: str = ""
    model: str = "gpt-5.4-mini"
    reasoning_effort: str = "low"
    temperature: float = 0.1
    max_output_tokens: int = 1200
    timeout_seconds: float = 20.0
    streaming_enabled: bool = False
    rerank_enabled: bool = False
    enabled: bool = False


@dataclass(frozen=True)
class LLMResult:
    answer: str
    structured: dict[str, Any] = field(default_factory=dict)
    provider: str = "disabled"
    model: str = ""
    reasoning_effort: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    token_cost: float = 0.0
    fallback_reason: str | None = None


class LLMProvider(Protocol):
    settings: LLMSettings

    def available(self) -> bool: ...

    def complete(self, *, question: str, context: list[KnowledgeMatch]) -> LLMResult | None: ...

    def stream(self, *, question: str, context: list[KnowledgeMatch]) -> Iterable[str]: ...


class DisabledLLMProvider:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings()

    def available(self) -> bool:
        return False

    def complete(self, *, question: str, context: list[KnowledgeMatch]) -> LLMResult | None:
        return None

    def stream(self, *, question: str, context: list[KnowledgeMatch]) -> Iterable[str]:
        return iter(())


class OpenAICompatibleChatLLM:
    """OpenAI-compatible chat completions provider."""

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def available(self) -> bool:
        return _provider_enabled(self.settings) and bool(self.settings.api_url and self.settings.model)

    def complete(self, *, question: str, context: list[KnowledgeMatch]) -> LLMResult | None:
        if not self.available():
            return None
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": _chat_messages(question, context),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
        }
        try:
            data = _post_json(self.settings, payload)
            choices = data.get("choices") or []
            if not choices:
                return None
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "").strip()
            if not content:
                return None
            usage = data.get("usage") or {}
            structured = _parse_structured(content)
            return LLMResult(
                answer=str(structured.get("answer") or content),
                structured=structured,
                provider="openai_compatible_chat",
                model=self.settings.model,
                reasoning_effort=self.settings.reasoning_effort,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chat LLM completion failed; falling back: %s", exc)
            return LLMResult(
                answer="",
                provider="openai_compatible_chat",
                model=self.settings.model,
                reasoning_effort=self.settings.reasoning_effort,
                fallback_reason=str(exc),
            )

    def stream(self, *, question: str, context: list[KnowledgeMatch]) -> Iterable[str]:
        if not self.available():
            return iter(())
        if not self.settings.streaming_enabled:
            result = self.complete(question=question, context=context)
            if result and result.answer:
                yield result.answer
            return
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": _chat_messages(question, context),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
            "stream": True,
        }
        yield from _stream_chat(self.settings, payload)


class OpenAIResponsesLLM:
    """OpenAI Responses API provider for structured RCA synthesis."""

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def available(self) -> bool:
        return _provider_enabled(self.settings) and bool(self.settings.api_url and self.settings.model)

    def complete(self, *, question: str, context: list[KnowledgeMatch]) -> LLMResult | None:
        if not self.available():
            return None
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _prompt(question, context)},
            ],
            "temperature": self.settings.temperature,
            "max_output_tokens": self.settings.max_output_tokens,
            "reasoning": {"effort": self.settings.reasoning_effort},
        }
        try:
            data = _post_json(self.settings, payload)
            content = _responses_text(data).strip()
            if not content:
                return None
            usage = data.get("usage") or {}
            structured = _parse_structured(content)
            return LLMResult(
                answer=str(structured.get("answer") or content),
                structured=structured,
                provider="openai_responses",
                model=self.settings.model,
                reasoning_effort=self.settings.reasoning_effort,
                prompt_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Responses LLM completion failed; falling back: %s", exc)
            return LLMResult(
                answer="",
                provider="openai_responses",
                model=self.settings.model,
                reasoning_effort=self.settings.reasoning_effort,
                fallback_reason=str(exc),
            )

    def stream(self, *, question: str, context: list[KnowledgeMatch]) -> Iterable[str]:
        if not self.available():
            return iter(())
        if not self.settings.streaming_enabled:
            result = self.complete(question=question, context=context)
            if result and result.answer:
                yield result.answer
            return
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _prompt(question, context)},
            ],
            "temperature": self.settings.temperature,
            "max_output_tokens": self.settings.max_output_tokens,
            "reasoning": {"effort": self.settings.reasoning_effort},
            "stream": True,
        }
        yield from _stream_responses(self.settings, payload)


class OpenAICompatibleLLM(OpenAICompatibleChatLLM):
    """Backward-compatible alias used by older tests and imports."""


def build_llm_provider(settings: LLMSettings) -> LLMProvider:
    provider = _provider_name(settings)
    if provider == "openai_responses":
        return OpenAIResponsesLLM(settings)
    if provider == "openai_compatible_chat":
        return OpenAICompatibleChatLLM(settings)
    return DisabledLLMProvider(settings)


def _provider_enabled(settings: LLMSettings) -> bool:
    provider = _provider_name(settings)
    return provider != "disabled" and (settings.enabled or provider in {"openai_responses", "openai_compatible_chat"})


def _provider_name(settings: LLMSettings) -> str:
    provider = (settings.provider or "disabled").lower()
    if provider == "disabled" and settings.enabled:
        return "openai_compatible_chat"
    return provider


def _post_json(settings: LLMSettings, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    response = requests.post(
        settings.api_url,
        headers=headers,
        json=payload,
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def _stream_json_lines(settings: LLMSettings, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    with requests.post(
        settings.api_url,
        headers=headers,
        json=payload,
        timeout=settings.timeout_seconds,
        stream=True,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line.replace("data:", "", 1).strip()
            if line == "[DONE]":
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


def _stream_chat(settings: LLMSettings, payload: dict[str, Any]) -> Iterable[str]:
    try:
        for data in _stream_json_lines(settings, payload):
            for choice in data.get("choices") or []:
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chat LLM stream failed; falling back to non-streaming completion: %s", exc)
        result = OpenAICompatibleChatLLM(settings).complete(
            question=_question_from_payload(payload),
            context=[],
        )
        if result and result.answer:
            yield result.answer


def _stream_responses(settings: LLMSettings, payload: dict[str, Any]) -> Iterable[str]:
    try:
        for data in _stream_json_lines(settings, payload):
            event_type = str(data.get("type") or "")
            if event_type in {"response.output_text.delta", "response.refusal.delta"} and data.get("delta"):
                yield str(data["delta"])
            elif data.get("output_text"):
                yield str(data["output_text"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Responses LLM stream failed; falling back to non-streaming completion: %s", exc)
        result = OpenAIResponsesLLM(settings).complete(
            question=_question_from_payload(payload),
            context=[],
        )
        if result and result.answer:
            yield result.answer


def _question_from_payload(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if messages:
        return str(messages[-1].get("content") or "")
    inputs = payload.get("input")
    if inputs:
        return str(inputs[-1].get("content") or "")
    return ""


def _chat_messages(question: str, context: list[KnowledgeMatch]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _prompt(question, context)},
    ]


def _system_prompt() -> str:
    return (
        "You are an RCA copilot. Answer only from the supplied evidence. "
        "Every diagnosis and repair recommendation must cite evidence_ids from the context. "
        "If evidence is insufficient, say what is missing and mark the claim as a hypothesis. "
        "Recommend only manual investigation runbooks. "
        "Do not propose automatic rollback, restart, scale, ticket execution, "
        "or any executor workflow. Return a compact JSON object."
    )


def _prompt(question: str, context: list[KnowledgeMatch]) -> str:
    lines = [
        f"Question: {question}",
        "",
        "Evidence context:",
    ]
    for index, match in enumerate(context, start=1):
        evidence_ids = (
            match.attributes.get("evidence_event_ids")
            or match.attributes.get("event_ids")
            or []
        )
        lines.extend(
            [
                f"[{index}] source={match.source} ref_id={match.ref_id} title={match.title} score={match.score}",
                f"evidence_ids={json.dumps(evidence_ids, ensure_ascii=False)}",
                f"chunk_kind={match.attributes.get('chunk_kind') or match.source}",
                f"recall_sources={','.join(match.recall_sources)}",
                f"score_breakdown={json.dumps(match.score_breakdown, sort_keys=True)}",
                match.content[:1800],
                "",
            ]
        )
    lines.extend(
        [
            "Return JSON with these keys:",
            "answer: string",
            "diagnosis: array of objects {claim, evidence_ids, confidence, status}",
            "supporting_evidence: array of objects {evidence_id, summary, source}",
            "repair_plan: array of objects {step, evidence_ids, manual_only}",
            "risks: array of strings",
            "open_questions: array of strings",
            "root_cause_summary: string",
            "supporting_citations: array of citation numbers like [1,2]",
            "missing_evidence: array of strings",
            "recommended_manual_runbooks: array of strings",
            "follow_up_questions: array of strings",
            "confidence_rationale: string",
        ]
    )
    return "\n".join(lines)


def _parse_structured(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"answer": content}
    return parsed if isinstance(parsed, dict) else {"answer": content}


def _responses_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    chunks: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks)
