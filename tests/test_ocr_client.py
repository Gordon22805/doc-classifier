import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.core.ocr_client import OCRClient
from backend.models.schemas import OCRProfile


class TestOCRClient:
    
    @pytest.fixture
    def client(self):
        return OCRClient(api_key="test-api-key")
    
    def test_is_available_with_key(self, client):
        """Проверка доступности с настроенным API ключом"""
        assert client.is_available()
    
    def test_is_available_without_key(self, monkeypatch):
        """Проверка доступности без API ключа и без своего base_url"""
        from backend.config import settings
        monkeypatch.setattr(settings, "openai_api_key", None)
        monkeypatch.setattr(settings, "vision_base_url", None)
        client = OCRClient(api_key=None)
        assert not client.is_available()
    
    @pytest.mark.asyncio
    async def test_recognize_unavailable(self, monkeypatch):
        """Ошибка при недоступном сервисе"""
        from backend.config import settings
        monkeypatch.setattr(settings, "openai_api_key", None)
        monkeypatch.setattr(settings, "vision_base_url", None)
        client = OCRClient(api_key=None)
        
        with pytest.raises(Exception) as exc_info:
            await client.recognize(b"image_data")
        
        assert "не настроен" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_recognize_success(self, client):
        """Успешное распознавание"""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Распознанный текст"))
        ]
        
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_completion
            
            result = await client.recognize(b"test_image")
            
            assert result.text == "Распознанный текст"
            assert result.confidence == 0.95
            assert "vision" in result.method
    
    @pytest.mark.asyncio
    async def test_recognize_with_profile(self, client):
        """Распознавание с профилем"""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Текст с высокой точностью"))
        ]
        
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_completion
            
            result = await client.recognize(b"test_image", profile=OCRProfile.ENHANCED)
            
            assert result.text == "Текст с высокой точностью"
            assert "enhanced" in result.method
            
            # Проверяем, что использован правильный промпт
            call_kwargs = mock_create.call_args[1]
            messages = call_kwargs['messages']
            prompt = messages[0]['content'][0]['text']
            assert "accuracy" in prompt.lower() or "degraded" in prompt.lower()
    
    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, client):
        """Повтор при rate limit"""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Success"))
        ]
        
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # Первая попытка - rate limit, вторая - успех
            mock_create.side_effect = [
                Exception("Rate limit exceeded"),
                mock_completion
            ]
            
            result = await client.recognize(b"test_image")
            
            assert result.text == "Success"
            assert mock_create.call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, client):
        """Повтор при timeout"""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Success"))
        ]
        
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # Первая попытка - timeout, вторая - успех
            mock_create.side_effect = [
                Exception("Request timeout"),
                mock_completion
            ]
            
            result = await client.recognize(b"test_image")
            
            assert result.text == "Success"
            assert mock_create.call_count == 2
    
    @pytest.mark.asyncio
    async def test_no_retry_on_other_errors(self, client):
        """Нет повтора для других ошибок"""
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # Обычная ошибка (не сетевая)
            mock_create.side_effect = Exception("Invalid API key")
            
            with pytest.raises(Exception) as exc_info:
                await client.recognize(b"test_image")
            
            assert "Invalid API key" in str(exc_info.value) or "OCR ошибка" in str(exc_info.value)
            # Только одна попытка, нет повторов
            assert mock_create.call_count == 1
    
    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, client):
        """Исчерпаны все попытки"""
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            # Все попытки - ошибка
            mock_create.side_effect = Exception("Rate limit exceeded")
            
            with pytest.raises(Exception) as exc_info:
                await client.recognize(b"test_image")
            
            # Проверяем наличие ключевых слов в сообщении об ошибке
            error_text = str(exc_info.value)
            assert "OCR" in error_text or "попыт" in error_text
            # Первая + max_retries повторов
            assert mock_create.call_count == client.max_retries + 1
    
    @pytest.mark.asyncio
    async def test_empty_response(self, client):
        """Обработка пустого ответа"""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content=""))
        ]
        
        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_completion
            
            result = await client.recognize(b"test_image")
            
            assert result.text == ""
            assert result.confidence == 0.95


class TestCustomProvider:
    """Работа через OpenAI-совместимый провайдер (Ollama, OpenRouter, LM Studio)"""

    def test_base_url_passed_to_client(self):
        client = OCRClient(api_key="test-key", base_url="http://127.0.0.1:11434/v1")
        assert client.is_available()
        assert "127.0.0.1:11434" in str(client.client.base_url)

    def test_local_provider_works_without_key(self):
        """Локальный сервер не требует ключа — подставляется заглушка"""
        client = OCRClient(api_key=None, base_url="http://127.0.0.1:11434/v1")
        assert client.is_available()

    def test_no_key_no_base_url_is_unavailable(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "openai_api_key", None)
        monkeypatch.setattr(settings, "vision_base_url", None)
        assert not OCRClient().is_available()

    def test_model_name_from_settings(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "vision_model", "qwen2.5vl:3b")
        client = OCRClient(api_key="k", base_url="http://localhost:11434/v1")
        assert client.model == "qwen2.5vl:3b"
