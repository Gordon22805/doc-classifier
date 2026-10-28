import json

import httpx
import pytest

from app.config import Settings
from app.llm_service import LLMBadResponse, LLMNotConfigured, LLMService, LLMTimeout

VALID = {
    "category": "PAYMENT",
    "intent": "DUPLICATE_CHARGE",
    "priority": "HIGH",
    "sentiment": "NEGATIVE",
    "confidence": 0.93,
}


def settings(**overrides):
    base = {
        "openrouter_api_key": "test-key",
        "openrouter_base_url": "https://llm.example.com/v1",
        "llm_model": "test-model",
    }
    base.update(overrides)
    return Settings(**base)


def completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_successful_call_sends_json_mode_and_returns_parsed():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=completion(json.dumps(VALID)))

    service = LLMService(settings(), transport=httpx.MockTransport(handler))
    result = await service.classify("С меня дважды списали деньги")

    assert result.intent == "DUPLICATE_CHARGE"
    assert captured["url"] == "https://llm.example.com/v1/chat/completions"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["auth"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_missing_configuration_raises_not_configured():
    service = LLMService(Settings(openrouter_api_key=None))

    with pytest.raises(LLMNotConfigured):
        await service.classify("текст")


@pytest.mark.asyncio
async def test_unauthorized_maps_to_not_configured():
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={}))
    service = LLMService(settings(), transport=transport)

    with pytest.raises(LLMNotConfigured):
        await service.classify("текст")


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    service = LLMService(settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(LLMTimeout):
        await service.classify("текст")


@pytest.mark.asyncio
async def test_non_json_content_raises_bad_response():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion("Извините, не могу"))
    )
    service = LLMService(settings(), transport=transport)

    with pytest.raises(LLMBadResponse, match="не JSON"):
        await service.classify("текст")


@pytest.mark.asyncio
async def test_unknown_category_from_model_raises_bad_response():
    bad = dict(VALID, category="BILLING")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion(json.dumps(bad)))
    )
    service = LLMService(settings(), transport=transport)

    with pytest.raises(LLMBadResponse, match="category"):
        await service.classify("текст")


@pytest.mark.asyncio
async def test_markdown_wrapped_json_is_accepted():
    wrapped = f"```json\n{json.dumps(VALID)}\n```"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion(wrapped))
    )
    service = LLMService(settings(), transport=transport)

    result = await service.classify("текст")

    assert result.category.value == "PAYMENT"


@pytest.mark.asyncio
async def test_unexpected_envelope_raises_bad_response():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"result": "no choices here"})
    )
    service = LLMService(settings(), transport=transport)

    with pytest.raises(LLMBadResponse):
        await service.classify("текст")
