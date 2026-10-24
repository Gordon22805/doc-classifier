import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

# Добавляем корневую директорию в PYTHONPATH
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))


@pytest.fixture
def mock_ocr_client():
    """Мок OCR клиента для тестов"""
    from backend.core.ocr_client import OCRClient
    from backend.models.schemas import OCRResponse
    
    client = OCRClient(api_key="test-key")
    
    async def mock_recognize(image_bytes, profile=None):
        """Мок распознавания"""
        return OCRResponse(
            text="Мок распознанный текст\nПаспорт РФ\n4500 123456\n20.01.2010",
            confidence=0.95,
            method="mock_gpt4_vision"
        )
    
    client.recognize = mock_recognize
    return client
