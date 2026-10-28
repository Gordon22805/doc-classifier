import json
import logging
import time
from typing import Any, Dict

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas import TicketClassification

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Ошибка обращения к OpenRouter или разбора ответа."""


class LLMNotConfigured(LLMError):
    pass


class LLMTimeout(LLMError):
    pass


class LLMBadResponse(LLMError):
    pass


class LLMService:
    def __init__(self, settings=None, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or get_settings()
        self._transport = transport

    def is_configured(self) -> bool:
        return self.settings.llm_configured

    async def classify(self, ticket_text: str) -> TicketClassification:
        if not self.is_configured():
            raise LLMNotConfigured(
                "OpenRouter не настроен: задайте OPENROUTER_API_KEY, "
                "OPENROUTER_BASE_URL и LLM_MODEL в .env"
            )

        payload: Dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(ticket_text)},
            ],
            "response_format": {"type": "json_object"},
        }
        url = self.settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.openrouter_api_key}"}

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.llm_timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("OpenRouter timeout за %.2f с", time.perf_counter() - started)
            raise LLMTimeout("OpenRouter не ответил за отведённое время") from exc
        except httpx.HTTPError as exc:
            logger.warning("OpenRouter недоступен: %s", type(exc).__name__)
            raise LLMError("Не удалось связаться с OpenRouter") from exc

        elapsed = time.perf_counter() - started
        if response.status_code == 401:
            raise LLMNotConfigured("OpenRouter отклонил ключ: проверьте OPENROUTER_API_KEY")
        if response.status_code == 429:
            logger.warning("OpenRouter: превышен лимит запросов, %.2f с", elapsed)
            raise LLMError("OpenRouter: превышен лимит запросов, попробуйте позже")
        if response.status_code == 403:
            logger.warning("OpenRouter вернул 403 за %.2f с", elapsed)
            raise LLMError("OpenRouter вернул 403: запрос заблокирован, проверьте ключ и сеть")
        if response.status_code >= 400:
            logger.warning("OpenRouter вернул %s за %.2f с", response.status_code, elapsed)
            raise LLMError(f"OpenRouter вернул HTTP {response.status_code}")

        raw = self._extract_content(response)
        logger.info("LLM ответила за %.2f с", elapsed)
        return self._parse(raw)

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponse("OpenRouter вернул неожиданную структуру ответа") from exc

    @staticmethod
    def _parse(raw: str) -> TicketClassification:
        text = raw.strip()
        if text.startswith("```"):
            # Модель иногда оборачивает JSON в markdown, несмотря на инструкцию
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMBadResponse("Модель вернула не JSON") from exc

        try:
            return TicketClassification.model_validate(parsed)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"]) or "ответ"
            raise LLMBadResponse(f"Некорректное поле {field}: {first['msg']}") from exc
