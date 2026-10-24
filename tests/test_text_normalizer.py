import pytest
from backend.core.text_normalizer import TextNormalizer


class TestTextNormalizer:
    
    @pytest.fixture
    def normalizer(self):
        return TextNormalizer()
    
    def test_basic_normalization(self, normalizer):
        """Тест базовой нормализации"""
        text = "Паспорт  ГРАЖДАНИНА   РФ"
        result = normalizer.normalize(text)
        assert result == "паспорт гражданина рф"
    
    def test_yo_replacement(self, normalizer):
        """Замена ё на е"""
        text = "Алёна Фёдоровна"
        result = normalizer.normalize(text)
        assert "ё" not in result
        assert "алена федоровна" == result
    
    def test_mixed_cyrillic_latin(self, normalizer):
        """Исправление смешанной кириллицы и латиницы"""
        text = "Mocквa"  # o и c латинские
        result = normalizer.normalize(text)
        assert result == "москва"
    
    def test_mrz_preservation(self, normalizer):
        """MRZ строки не должны изменяться"""
        mrz = "P<RUSIVANOV<<IVAN<<<<<<<<<<<<<<<<<<<<<"
        result = normalizer.normalize(mrz)
        # MRZ содержит латиницу и должна сохраниться
        assert "<" in result
        assert "rus" in result
    
    def test_document_number_preservation(self, normalizer):
        """Номера документов не должны изменяться"""
        text = "серия 4509 номер 123456"
        result = normalizer.normalize(text)
        assert "4509" in result
        assert "123456" in result
    
    def test_whitespace_normalization(self, normalizer):
        """Нормализация пробелов"""
        text = "текст  с   лишними    пробелами"
        result = normalizer.normalize(text)
        assert "  " not in result
        assert result == "текст с лишними пробелами"
    
    def test_dash_normalization(self, normalizer):
        """Нормализация дефисов"""
        text = "Иванов–Петров—Сидоров"  # разные дефисы
        result = normalizer.normalize(text)
        assert result == "иванов-петров-сидоров"
    
    def test_number_sign(self, normalizer):
        """Символ номера"""
        text = "№ 123"
        result = normalizer.normalize(text)
        assert result == "no 123"
    
    def test_control_characters(self, normalizer):
        """Удаление управляющих символов"""
        text = "текст\x00с\x01управляющими\x02символами"
        result = normalizer.normalize(text)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
    
    def test_ocr_errors_correction(self, normalizer):
        """Коррекция типичных OCR ошибок в русских словах"""
        # c вместо с, o вместо о в русском слове
        text = "дoкумeнт"  # латинские o и e
        result = normalizer.normalize(text)
        assert result == "документ"
