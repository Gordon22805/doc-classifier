import base64
import asyncio
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from backend.models.schemas import OCRResponse, OCRProfile
from backend.config import settings

logger = logging.getLogger(__name__)


class OCRClient:
    """Асинхронный клиент OCR через vision-модель (OpenAI-совместимый API)"""
    
    # Промпты для разных профилей
    PROFILES = {
        OCRProfile.ORIGINAL: "Extract all text from this document image. Preserve the original structure and formatting.",
        OCRProfile.FOCUSED: "Extract all text from this document image with high accuracy. Pay special attention to small text and details.",
        OCRProfile.ENHANCED: "Extract all text from this document image. Use maximum accuracy for low-quality or degraded images. Extract even faint or unclear text.",
        OCRProfile.TILE: "Extract all visible text from this document fragment. Be thorough and capture all text elements.",
    }
    
    # Локальные серверы ключ не проверяют, им подставляем заглушку.
    LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        # Пустая строка в .env трактуется как «ключ не задан»
        self.api_key = (api_key or settings.openai_api_key or "").strip() or None
        self.model = settings.vision_model or "qwen/qwen2.5-vl-72b-instruct:free"
        self.base_url = (base_url or settings.vision_base_url or "").strip() or None
        self.request_timeout = settings.ocr_request_timeout
        self.max_retries = settings.ocr_max_retries
        
        self.client: Optional[AsyncOpenAI] = None
        key = self.api_key or self._local_placeholder_key()
        if key:
            kwargs = {
                "api_key": key,
                "timeout": httpx.Timeout(
                    self.request_timeout,
                    connect=settings.ocr_connect_timeout,
                ),
                # Повторы делает наш цикл в recognize(), иначе SDK умножает
                # число запросов и время ожидания растёт в разы.
                "max_retries": 0,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = AsyncOpenAI(**kwargs)
        else:
            logger.warning(
                "OCR не настроен: не задан OPENAI_API_KEY. "
                "Будут обрабатываться только файлы с текстовым слоем."
            )

    def _local_placeholder_key(self) -> Optional[str]:
        """Заглушка ключа — только для локального сервера, не для облака."""
        if not self.base_url:
            return None
        host = (urlparse(self.base_url).hostname or "").lower()
        return "local" if host in self.LOCAL_HOSTS else None
    
    def is_available(self) -> bool:
        """Проверка доступности OCR сервиса"""
        return self.client is not None
    
    async def recognize(
        self,
        image_data: bytes,
        profile: OCRProfile = OCRProfile.ORIGINAL,
        use_unwarping: bool = False
    ) -> OCRResponse:
        """
        Распознавание текста на изображении через vision-модель
        
        Args:
            image_data: Байты изображения
            profile: Профиль распознавания (определяет промпт)
            use_unwarping: Игнорируется (для совместимости)
        
        Returns:
            OCRResponse с распознанным текстом
        
        Raises:
            Exception: При недоступности сервиса или ошибке распознавания
        """
        if not self.is_available():
            raise Exception(
                "OCR не настроен. Задайте OPENAI_API_KEY в .env "
                "(ключ OpenRouter: https://openrouter.ai/keys)."
            )
        
        client = self.client
        # Подготовка изображения
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        # Выбираем промпт по профилю
        prompt = self.PROFILES.get(profile, self.PROFILES[OCRProfile.ORIGINAL])
        
        # Выполняем запрос с повторами
        attempt = 0
        last_error = None
        
        while attempt <= self.max_retries:
            try:
                logger.debug(f"OCR попытка {attempt + 1}/{self.max_retries + 1}, профиль: {profile}")
                
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}",
                                        "detail": "high"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=4096,
                    temperature=0.0
                )
                
                # Извлекаем текст
                extracted_text = response.choices[0].message.content or ""
                
                logger.info(f"OCR успешно, извлечено {len(extracted_text)} символов")
                
                return OCRResponse(
                    text=extracted_text,
                    confidence=0.95,
                    method=f"vision_{profile.value}"
                )
                
            except Exception as e:
                last_error = e
                logger.warning(f"OCR ошибка (попытка {attempt + 1}): {e}")
                
                # Определяем, нужно ли повторить
                should_retry = self._should_retry(e, attempt)
                
                if not should_retry:
                    logger.error(f"OCR не удался, повтор не требуется: {e}")
                    raise Exception(f"OCR ошибка: {e}")
                
                # Экспоненциальная задержка
                if attempt < self.max_retries:
                    delay = min(2 ** attempt, 10)
                    logger.info(f"Ожидание {delay}с перед повтором")
                    await asyncio.sleep(delay)
                
                attempt += 1
        
        # Все попытки исчерпаны
        raise Exception(f"OCR не удался после {self.max_retries + 1} попыток: {last_error}")
    
    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """Определяет, нужно ли повторять запрос"""
        if attempt >= self.max_retries:
            return False
        
        error_str = str(error).lower()
        
        # Всегда повторяем для сетевых ошибок и rate limits
        retry_keywords = [
            "timeout", "connection", "network", 
            "rate limit", "429", "503", "500", "502", "504"
        ]
        
        return any(keyword in error_str for keyword in retry_keywords)
