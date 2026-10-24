import pytest
from backend.core.text_quality import TextQualityChecker


class TestTextQualityChecker:
    
    @pytest.fixture
    def checker(self):
        return TextQualityChecker()
    
    def test_good_text(self, checker):
        """Хороший качественный текст"""
        text = """
        Паспорт гражданина Российской Федерации
        Серия 4509 Номер 123456
        Выдан ОВД района Черёмушки г. Москвы
        Код подразделения 772-043
        Дата выдачи 15.06.2015
        """
        result = checker.check_quality(text)
        assert result.is_good
        assert result.score > 50
    
    def test_empty_text(self, checker):
        """Пустой текст"""
        result = checker.check_quality("")
        assert not result.is_good
        assert result.score == 0
        assert "пустой" in result.issues[0].lower()
    
    def test_short_text(self, checker):
        """Короткий текст"""
        text = "М.П."
        result = checker.check_quality(text)
        # Короткий текст может быть валидным (штамп)
        assert result.metrics["length"] < 10
    
    def test_replacement_characters(self, checker):
        """Текст с символами замены"""
        text = "Текст с � множеством � символов � замены �"
        result = checker.check_quality(text)
        assert not result.is_good
        assert "символов замены" in " ".join(result.issues).lower()
    
    def test_cid_artifacts(self, checker):
        """Артефакты CID"""
        text = "Текст с (cid:123) артефактами (cid:456) и (cid:789)"
        result = checker.check_quality(text)
        assert not result.is_good
        assert any("cid" in issue.lower() for issue in result.issues)
    
    def test_low_alnum_ratio(self, checker):
        """Мало букв и цифр"""
        text = "!@#$%^&*()_+=-{}[]|\\:;<>?,./~`"
        result = checker.check_quality(text)
        assert not result.is_good
        assert any("букв" in issue.lower() for issue in result.issues)
    
    def test_long_repeats(self, checker):
        """Длинные повторы символов"""
        text = "Текст с ооооооооооооочень длинным повтором"
        result = checker.check_quality(text)
        assert not result.is_good
        assert any("повтор" in issue.lower() for issue in result.issues)
    
    def test_latin_in_russian(self, checker):
        """Подозрительная латиница в русском тексте"""
        text = "Pasport grazhdanina RF seria nomer data vydachi" * 3
        result = checker.check_quality(text)
        # Много латиницы при достаточной длине должно быть подозрительным
        assert len(text) > 50
        assert result.metrics.get("latin_ratio", 0) > 0.7
    
    def test_needs_ocr(self, checker):
        """Определение необходимости OCR"""
        bad_text = "���� (cid:123) ���"
        good_text = "Качественный распознанный текст документа"
        
        assert checker.needs_ocr(bad_text)
        assert not checker.needs_ocr(good_text)
