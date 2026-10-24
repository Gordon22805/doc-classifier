import re
import unicodedata
from typing import Set


class TextNormalizer:
    """Нормализация текста перед классификацией"""
    
    # Таблица замены похожих кириллических и латинских символов
    CYRILLIC_TO_LATIN = {
        'а': 'a', 'в': 'b', 'е': 'e', 'к': 'k', 'м': 'm',
        'н': 'h', 'о': 'o', 'р': 'p', 'с': 'c', 'т': 't',
        'у': 'y', 'х': 'x', 'А': 'A', 'В': 'B', 'Е': 'E',
        'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P',
        'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X'
    }
    
    LATIN_TO_CYRILLIC = {v: k for k, v in CYRILLIC_TO_LATIN.items()}
    
    def __init__(self):
        self._cyrillic_chars = set('абвгдежзийклмнопрстуфхцчшщъыьэюяёАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯЁ')
    
    def normalize(self, text: str) -> str:
        """Полная нормализация текста"""
        if not text:
            return ""
        
        # Unicode NFKC
        text = unicodedata.normalize('NFKC', text)
        
        # Нижний регистр
        text = text.lower()
        
        # Замена ё на е
        text = text.replace('ё', 'е')
        
        # Нормализация пробелов и невидимых символов
        text = self._normalize_whitespace(text)
        
        # Нормализация дефисов
        text = self._normalize_dashes(text)
        
        # Нормализация символа номера
        text = text.replace('№', 'no')
        
        # Коррекция смешанных латинских и кириллических символов
        text = self._fix_mixed_charset(text)
        
        return text
    
    def _normalize_whitespace(self, text: str) -> str:
        """Нормализация пробелов"""
        # Заменяем все виды пробелов на обычный пробел
        text = re.sub(r'[\u00A0\u1680\u2000-\u200B\u202F\u205F\u3000\uFEFF]+', ' ', text)
        # Удаляем управляющие символы кроме переноса строки
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
        # Нормализуем переносы строк
        text = re.sub(r'\r\n', '\n', text)
        # Убираем лишние пробелы
        text = re.sub(r' +', ' ', text)
        return text
    
    def _normalize_dashes(self, text: str) -> str:
        """Нормализация дефисов и тире"""
        # Различные виды дефисов и тире заменяем на обычный дефис
        dash_chars = [
            '\u002D',  # Hyphen-minus
            '\u2010',  # Hyphen
            '\u2011',  # Non-breaking hyphen
            '\u2012',  # Figure dash
            '\u2013',  # En dash
            '\u2014',  # Em dash
            '\u2015',  # Horizontal bar
        ]
        for dash in dash_chars:
            text = text.replace(dash, '-')
        return text
    
    def _fix_mixed_charset(self, text: str) -> str:
        """Исправление смешанных латинских и кириллических символов в кириллических словах"""
        words = text.split()
        fixed_words = []
        
        for word in words:
            # Пропускаем специальные последовательности (MRZ, коды)
            if self._is_special_sequence(word):
                fixed_words.append(word)
                continue
            
            # Проверяем, является ли слово преимущественно кириллическим
            if self._is_mostly_cyrillic(word):
                fixed_word = self._replace_latin_with_cyrillic(word)
                fixed_words.append(fixed_word)
            else:
                fixed_words.append(word)
        
        return ' '.join(fixed_words)
    
    def _is_special_sequence(self, word: str) -> bool:
        """Проверка, является ли слово специальной последовательностью (MRZ, номер и т.д.)"""
        # MRZ строки
        if re.match(r'^[A-Z0-9<]+$', word.upper()) and len(word) > 10:
            return True
        # Коды вида RUS, номера документов
        if re.match(r'^[A-Z]{3}$', word.upper()):
            return True
        if re.match(r'^\d+[-/]?\d*$', word):
            return True
        # Серия-номер паспорта
        if re.match(r'^\d{2}\s?\d{2}\s?\d{6}$', word.replace(' ', '')):
            return True
        return False
    
    def _is_mostly_cyrillic(self, word: str) -> bool:
        """Проверка, является ли слово преимущественно кириллическим"""
        if len(word) < 2:
            return False
        
        cyrillic_count = sum(1 for c in word if c in self._cyrillic_chars)
        letter_count = sum(1 for c in word if c.isalpha())
        
        if letter_count == 0:
            return False
        
        return cyrillic_count / letter_count >= 0.3
    
    def _replace_latin_with_cyrillic(self, word: str) -> str:
        """Замена латинских символов на кириллические в слове"""
        result = []
        for char in word:
            if char in self.LATIN_TO_CYRILLIC:
                result.append(self.LATIN_TO_CYRILLIC[char])
            else:
                result.append(char)
        return ''.join(result)
    
    def preserve_original(self, text: str) -> str:
        """Минимальная нормализация для сохранения оригинальных кодов"""
        if not text:
            return ""
        return unicodedata.normalize('NFKC', text)
