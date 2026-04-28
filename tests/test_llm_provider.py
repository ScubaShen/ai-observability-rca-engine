from rca_engine.models import KnowledgeMatch
from rca_engine.rag.llm import (
    DisabledLLMProvider,
    LLMSettings,
    OpenAICompatibleChatLLM,
    OpenAIResponsesLLM,
    build_llm_provider,
)


def test_disabled_provider_is_not_available():
    provider = build_llm_provider(LLMSettings(provider="disabled"))

    assert isinstance(provider, DisabledLLMProvider)
    assert provider.available() is False
    assert provider.complete(question="why?", context=[]) is None


def test_legacy_enabled_setting_maps_to_chat_provider():
    provider = build_llm_provider(
        LLMSettings(enabled=True, api_url="http://llm.example/v1/chat/completions", model="gpt-test")
    )

    assert isinstance(provider, OpenAICompatibleChatLLM)
    assert provider.available() is True


def test_responses_provider_payload_contains_reasoning(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output_text": '{"answer":"Use the cited evidence.","supporting_citations":[1]}',
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("rca_engine.rag.llm.requests.post", fake_post)
    provider = OpenAIResponsesLLM(
        LLMSettings(
            provider="openai_responses",
            api_url="http://llm.example/v1/responses",
            api_key="secret",
            model="gpt-test",
            reasoning_effort="high",
        )
    )

    result = provider.complete(
        question="What happened?",
        context=[KnowledgeMatch(source="rca_result", title="RCA", score=0.9, content="Evidence")],
    )

    assert result is not None
    assert result.answer == "Use the cited evidence."
    assert captured["json"]["model"] == "gpt-test"
    assert captured["json"]["reasoning"]["effort"] == "high"
    assert captured["headers"]["Authorization"] == "Bearer secret"
