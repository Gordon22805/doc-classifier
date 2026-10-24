import re
from backend.models.schemas import TextQualityResult
from backend.config import settings


class TextQualityChecker:
    """Проверка качества извлечённого текста"""
    
    def __init__(self):
        self.min_text_length = settings.min_text_length
        self.max_replacement_char_ratio = settings.max_replacement_char_ratio
        self.min_alnum_ratio = settings.min_alnum_ratio
        self.max_repeat_length = settings.max_repeat_length
        self.max_cid_ratio = settings.max_cid_ratio
    
    def check_quality(self, text: str, is_ocr: bool = False, ocr_confidence: float = None) -> TextQualityResult:
        """
        Проверка качества текста
        
        Args:
            text: Текст для проверки
            is_ocr: Получен ли текст через OCR
            ocr_confidence: Уверенность OCR (если применимо)
        
        Returns:
            TextQualityResult с оценкой качества
        """
        issues = []
        metrics = {}
        score = 100.0
        
        if not text or not text.strip():
            return TextQualityResult(
                is_good=False,
                score=0,
                issues=["Текст пустой"],
                metrics={"length": 0}
            )
        
        text_length = len(text.strip())
        metrics["length"] = text_length
        
        # 1. Проверка минимальной длины
        if text_length < self.min_text_length:
            # Короткий текст не всегда плохой (штампы, подписи)
            # Проверяем другие метрики более строго
            issues.append(f"Короткий текст ({text_length} символов)")
            score -= 10
        
        # 2. Проверка на replacement characters
        replacement_chars = text.count('\ufffd') + text.count('�')
        replacement_ratio = replacement_chars / text_length if text_length > 0 else 0
        metrics["replacement_ratio"] = replacement_ratio
        
        if replacement_ratio > self.max_replacement_char_ratio:
            issues.append(f"Много символов замены ({replacement_ratio:.1%})")
            score -= 30
        
        # 3. Проверка на CID артефакты
        cid_count = len(re.findall(r'\(cid:\d+\)', text))
        cid_ratio = (cid_count * 8) / text_length if text_length > 0 else 0  # ~8 символов на cid
        metrics["cid_ratio"] = cid_ratio
        
        if cid_ratio > self.max_cid_ratio:
            issues.append(f"CID артефакты ({cid_count} вхождений)")
            score -= 40
        
        # 4. Проверка доли букв и цифр
        alnum_count = sum(1 for c in text if c.isalnum())
        alnum_ratio = alnum_count / text_length if text_length > 0 else 0
        metrics["alnum_ratio"] = alnum_ratio
        
        if alnum_ratio < self.min_alnum_ratio:
            issues.append(f"Мало букв и цифр ({alnum_ratio:.1%})")
            score -= 25
        
        # 5. Проверка на длинные повторы символов
        max_repeat = max((len(match.group(0)) for match in re.finditer(r'(.)\1+', text)), default=0)
        metrics["max_repeat"] = max_repeat
        
        if max_repeat > self.max_repeat_length:
            issues.append(f"Длинный повтор символов ({max_repeat})")
            score -= 15
        
        # 6. Проверка на управляющие символы
        control_chars = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
        control_ratio = control_chars / text_length if text_length > 0 else 0
        metrics["control_ratio"] = control_ratio
        
        if control_ratio > 0.05:
            issues.append(f"Много управляющих символов ({control_ratio:.1%})")
            score -= 20
        
        # 7. Проверка на подозрительное распознавание русскоязычной страницы латиницей
        if text_length > 50:  # Только для достаточно длинных текстов
            cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
            latin_count = sum(1 for c in text if c.isalpha() and c.isascii())
            total_letters = cyrillic_count + latin_count
            
            if total_letters > 20:
                latin_ratio = latin_count / total_letters
                metrics["latin_ratio"] = latin_ratio
                
                # Если преобладает латиница, но есть следы кириллицы - подозрительно
                if latin_ratio > 0.7 and cyrillic_count > 5:
                    issues.append(f"Подозрительное преобладание латиницы ({latin_ratio:.1%})")
                    score -= 20
        
        # 8. Высокая уверенность OCR не гарантирует качество
        if is_ocr and ocr_confidence and ocr_confidence > 0.9:
            # Всё равно проверяем другие метрики
            metrics["ocr_confidence"] = ocr_confidence
        
        # Итоговая оценка
        score = max(0, score)
        
        # Текст считается хорошим только если:
        # 1. Score >= 50
        # 2. Нет критических проблем (см. ниже)
        has_critical_issue = (
            replacement_ratio > 0.10 or
            cid_ratio > 0.20 or
            alnum_ratio < 0.40 or
            max_repeat > 10
        )
        
        is_good = score >= 50 and not has_critical_issue
        
        return TextQualityResult(
            is_good=is_good,
            score=score,
            issues=issues,
            metrics=metrics
        )
    
    def needs_ocr(self, text: str) -> bool:
        """Определяет, нужен ли OCR для текста"""
        quality = self.check_quality(text)
        return not quality.is_good
