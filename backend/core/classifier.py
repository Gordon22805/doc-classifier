import re
import logging
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict, Counter
import math

from backend.models.schemas import DocumentType, ClassificationCandidate
from backend.config import settings

logger = logging.getLogger(__name__)


class DocumentClassifier:
    """Классификатор документов на основе правил"""
    
    def __init__(self):
        self.min_score = settings.min_classification_score
        self.min_margin = settings.min_score_margin
        
        # Инициализация n-gram модели
        self._ngram_idf: Dict[str, float] = {}
        self._document_signatures: Dict[DocumentType, Set[str]] = {}
    
    def classify(self, text: str, filename: Optional[str] = None) -> Tuple[DocumentType, float, List[ClassificationCandidate]]:
        """
        Классификация документа
        
        Returns:
            (doc_type, confidence_score, all_candidates)
        """
        if not text or not text.strip():
            return DocumentType.UNKNOWN, 0, []
        
        candidates: List[ClassificationCandidate] = []
        
        # 1. Проверка имени файла
        if filename:
            file_candidate = self._check_filename_hint(text, filename)
            if file_candidate:
                candidates.append(file_candidate)
        
        # 2. Структурные признаки ЕГРН
        egrn_candidate = self._check_egrn_structural(text)
        if egrn_candidate:
            candidates.append(egrn_candidate)
        
        # 3. Точные специфичные заголовки
        exact_candidate = self._check_exact_titles(text)
        if exact_candidate:
            candidates.append(exact_candidate)
        
        # 4. Нечёткое совпадение заголовков
        fuzzy_candidate = self._check_fuzzy_titles(text)
        if fuzzy_candidate:
            candidates.append(fuzzy_candidate)
        
        # 5. Паспортные признаки
        passport_candidate = self._check_passport_features(text)
        if passport_candidate:
            candidates.append(passport_candidate)
        
        # 6. Номера форм с обязательными фразами
        form_candidate = self._check_form_numbers(text)
        if form_candidate:
            candidates.append(form_candidate)
        
        # 7. Взвешенный скоринг
        scoring_candidates = self._score_all_types(text)
        candidates.extend(scoring_candidates)
        
        # 8. N-граммы (если обучена модель)
        if self._ngram_idf:
            ngram_candidate = self._check_ngrams(text)
            if ngram_candidate:
                candidates.append(ngram_candidate)
        
        # Объединяем кандидатов с одинаковым типом
        merged = self._merge_candidates(candidates)
        
        # Сортируем по убыванию score
        merged.sort(key=lambda x: x.score, reverse=True)
        
        if not merged:
            # Если ни один кандидат не найден, возвращаем базовый UNKNOWN
            unknown_candidate = ClassificationCandidate(
                doc_type=DocumentType.UNKNOWN,
                score=0,
                rule_name="no_match",
                details={}
            )
            return DocumentType.UNKNOWN, 0, [unknown_candidate]
        
        best = merged[0]
        second_score = merged[1].score if len(merged) > 1 else 0
        margin = best.score - second_score
        
        # Проверяем пороги
        if best.score < self.min_score or margin < self.min_margin:
            return DocumentType.UNKNOWN, best.score, merged[:5]
        
        return best.doc_type, best.score, merged[:5]
    
    def _check_filename_hint(self, text: str, filename: str) -> Optional[ClassificationCandidate]:
        """Роль из имени файла + подтверждение по тексту"""
        filename_lower = filename.lower()
        
        hints = {
            "паспорт": DocumentType.PASSPORT,
            "passport": DocumentType.PASSPORT,
            "егрн": DocumentType.EGRN,
            "дкп": DocumentType.DKP,
            "договор купли": DocumentType.DKP,
            "пдкп": DocumentType.PDKP,
            "предварительный договор": DocumentType.PDKP,
            "дду": DocumentType.DDU,
            "долевого участия": DocumentType.DDU,
            "загс": DocumentType.ZAGS,
            "брак": DocumentType.ZAGS,
            "наследств": DocumentType.INHERITANCE,
            "ежд": DocumentType.EZD,
            "ндфл": DocumentType.NDFL,
            "2-ндфл": DocumentType.NDFL,
            "справка 2": DocumentType.NDFL,
        }
        
        for hint, doc_type in hints.items():
            if hint in filename_lower:
                # Проверяем подтверждение в тексте
                if self._has_text_confirmation(text, doc_type):
                    return ClassificationCandidate(
                        doc_type=doc_type,
                        score=3.0,
                        rule_name="filename_with_confirmation",
                        details={"filename": filename, "hint": hint}
                    )
        
        return None
    
    def _has_text_confirmation(self, text: str, doc_type: DocumentType) -> bool:
        """Проверка подтверждения типа документа в тексте"""
        confirmations = {
            DocumentType.PASSPORT: ["паспорт", "гражданин"],
            DocumentType.EGRN: ["росреестр", "кадастр", "егрн"],
            DocumentType.DKP: ["договор", "купли", "продажи"],
            DocumentType.PDKP: ["предварительный", "договор"],
            DocumentType.DDU: ["долевого участия", "дду"],
            DocumentType.ZAGS: ["загс", "о рождении", "о заключении брака"],
            DocumentType.INHERITANCE: ["наследств"],
            DocumentType.EZD: ["единый жилищный документ", "ежд"],
            DocumentType.NDFL: ["ндфл", "2-ндфл"],
        }
        
        keywords = confirmations.get(doc_type, [])
        return any(kw in text for kw in keywords)
    
    def _check_egrn_structural(self, text: str) -> Optional[ClassificationCandidate]:
        """Структурные признаки ЕГРН - требуется минимум 3 независимые группы"""
        groups_found = 0
        details = {}
        
        # Группа 1: Кадастровые данные
        cadastral_patterns = [
            r'\d{2}:\d{2}:\d{6,7}:\d+',  # Кадастровый номер
            r'кадастровый\s+номер',
            r'условный\s+номер'
        ]
        if any(re.search(p, text) for p in cadastral_patterns):
            groups_found += 1
            details["cadastral"] = True
        
        # Группа 2: Стоимость и оценка
        value_patterns = [
            r'кадастровая\s+стоимость',
            r'рыночная\s+стоимость',
            r'инвентаризационная\s+стоимость'
        ]
        if any(re.search(p, text) for p in value_patterns):
            groups_found += 1
            details["valuation"] = True
        
        # Группа 3: Правообладатель и права
        rights_patterns = [
            r'правообладател',
            r'вид\s+права',
            r'собственност',
            r'доля\s+в\s+праве'
        ]
        if any(re.search(p, text) for p in rights_patterns):
            groups_found += 1
            details["rights"] = True
        
        # Группа 4: Состояние записи и регистрация
        registration_patterns = [
            r'запись\s+регистрации',
            r'государственная\s+регистрация',
            r'дата\s+регистрации'
        ]
        if any(re.search(p, text) for p in registration_patterns):
            groups_found += 1
            details["registration"] = True
        
        # Группа 5: Сведения об объекте
        object_patterns = [
            r'назначение.*?(?:жилое|нежилое)',
            r'площадь.*?\d+[.,]\d+\s*м',
            r'адрес.*?объекта',
            r'местоположение'
        ]
        if any(re.search(p, text, re.DOTALL) for p in object_patterns):
            groups_found += 1
            details["object_info"] = True
        
        # Группа 6: Реквизиты Росреестра
        rosreestr_patterns = [
            r'росреестр',
            r'управление\s+федеральной\s+службы',
            r'егрн'
        ]
        if any(re.search(p, text) for p in rosreestr_patterns):
            groups_found += 1
            details["rosreestr"] = True
        
        if groups_found >= 3:
            score = 4.0 + (groups_found - 3) * 0.5  # Бонус за дополнительные группы
            return ClassificationCandidate(
                doc_type=DocumentType.EGRN,
                score=score,
                rule_name="egrn_structural",
                details={"groups_found": groups_found, **details}
            )
        
        return None
    
    def _check_exact_titles(self, text: str) -> Optional[ClassificationCandidate]:
        """Точные специфичные заголовки"""
        exact_titles = {
            DocumentType.PDKP: [
                "предварительный договор купли-продажи",
                "предварительный договор купли продажи"
            ],
            DocumentType.DKP: [
                "договор купли-продажи",
                "договор купли продажи"
            ],
            DocumentType.DDU: [
                "договор участия в долевом строительстве",
                "договор долевого участия"
            ],
            DocumentType.EZD: [
                "единый жилищный документ"
            ],
            DocumentType.PASSPORT: [
                "паспорт гражданина российской федерации"
            ]
        }
        
        # Берём первые 500 символов для проверки заголовка
        header = text[:500]
        
        for doc_type, titles in exact_titles.items():
            for title in titles:
                if title in header:
                    return ClassificationCandidate(
                        doc_type=doc_type,
                        score=5.0,
                        rule_name="exact_title",
                        details={"title": title}
                    )
        
        return None
    
    def _check_fuzzy_titles(self, text: str) -> Optional[ClassificationCandidate]:
        """Нечёткое совпадение значимых токенов заголовка"""
        # Реализация упрощённая: проверяем ключевые слова с покрытием
        header = text[:500]
        
        fuzzy_patterns = {
            DocumentType.ACCOUNTING: {
                "keywords": ["бухгалтерский", "баланс", "отчет", "форма"],
                "min_coverage": 0.75
            },
            DocumentType.PAYMENT_ORDER: {
                "keywords": ["платежное", "поручение", "банк"],
                "min_coverage": 0.67
            },
            DocumentType.REFERENCE: {
                "keywords": ["справка", "выдана", "подтверждение"],
                "min_coverage": 0.67
            }
        }
        
        best_candidate = None
        best_coverage = 0
        
        for doc_type, pattern in fuzzy_patterns.items():
            keywords = pattern["keywords"]
            min_cov = pattern["min_coverage"]
            
            found = sum(1 for kw in keywords if kw in header)
            coverage = found / len(keywords)
            
            if coverage >= min_cov and coverage > best_coverage:
                best_coverage = coverage
                best_candidate = ClassificationCandidate(
                    doc_type=doc_type,
                    score=3.0 * coverage,
                    rule_name="fuzzy_title",
                    details={"coverage": coverage, "keywords_found": found}
                )
        
        return best_candidate
    
    def _check_passport_features(self, text: str) -> Optional[ClassificationCandidate]:
        """Комплексная проверка паспортных признаков"""
        score = 0
        details = {}
        
        # 1. Название документа
        if "паспорт" in text:
            score += 1.5
            details["title"] = True
        
        # 2. Серия и номер (4400 123456, 44 00 123456, «Серия 45 00 № 123456»)
        passport_number = re.search(
            r'\d{2}\s?\d{2}\s*(?:№|номер|n)?\s*\d{6}',
            text
        )
        if passport_number:
            score += 2.0
            details["number"] = True
        
        # 3. Код подразделения (формат XXX-XXX)
        dept_code = re.search(r'\d{3}-\d{3}', text)
        if dept_code:
            score += 1.5
            details["dept_code"] = True
        
        # 4. Даты (дата рождения, дата выдачи)
        dates = re.findall(r'\d{2}\.\d{2}\.\d{4}', text)
        if len(dates) >= 2:
            score += 1.0
            details["dates"] = len(dates)
        
        # 5. Персональные поля
        personal_fields = ["фамилия", "имя", "отчество", "пол", "место рождения"]
        found_fields = sum(1 for field in personal_fields if field in text)
        if found_fields >= 3:
            score += 1.0
            details["personal_fields"] = found_fields
        
        # 6. MRZ и RUS
        has_mrz = False
        if "p<rus" in text or re.search(r'<<+', text):
            score += 1.5
            details["mrz"] = True
            has_mrz = True
        
        # 7. Дополнительный признак: красная полоса (визуальный, здесь не применим)
        # В реальности потребуется анализ изображения
        
        # Красная полоса сама по себе недостаточна
        # Требуем минимум 2 признака: явный заголовок «паспорт» или один из
        # структурных (номер, код подразделения, дата, MRZ)
        core_features = sum([
            details.get("title", False),
            details.get("number", False),
            details.get("dept_code", False),
            len(dates) >= 1,
            has_mrz
        ])
        
        if score >= 3.0 and core_features >= 2:
            return ClassificationCandidate(
                doc_type=DocumentType.PASSPORT,
                score=score,
                rule_name="passport_features",
                details=details
            )
        
        return None
    
    def _check_form_numbers(self, text: str) -> Optional[ClassificationCandidate]:
        """Номер формы + обязательная фраза"""
        form_rules = {
            "0401060": {
                "doc_type": DocumentType.PAYMENT_ORDER,
                "required_phrase": "платежное поручение"
            },
            "0710001": {
                "doc_type": DocumentType.ACCOUNTING,
                "required_phrase": "бухгалтерский баланс"
            },
            "1122035": {
                "doc_type": DocumentType.REFERENCE,
                "required_phrase": "справка"
            }
        }
        
        for form_num, rule in form_rules.items():
            if form_num in text and rule["required_phrase"] in text:
                return ClassificationCandidate(
                    doc_type=rule["doc_type"],
                    score=4.0,
                    rule_name="form_number",
                    details={"form": form_num, "phrase": rule["required_phrase"]}
                )
        
        return None
    
    def _score_all_types(self, text: str) -> List[ClassificationCandidate]:
        """Взвешенный скоринг для всех типов"""
        scores: Dict[DocumentType, float] = defaultdict(float)
        details_map: Dict[DocumentType, Dict] = defaultdict(dict)
        
        # Определяем положительные и отрицательные признаки для каждого типа
        
        # НДФЛ
        if "2-ндфл" in text or "справка о доходах" in text:
            scores[DocumentType.NDFL] += 3.0
            details_map[DocumentType.NDFL]["form_2ndfl"] = True
        if "налоговый агент" in text:
            scores[DocumentType.NDFL] += 1.0
        
        # СФР
        if "социальный фонд" in text or "пенсионный фонд" in text:
            scores[DocumentType.SFR] += 2.0
            details_map[DocumentType.SFR]["sfr_mention"] = True
        if re.search(r'снилс.*?\d{3}-\d{3}-\d{3}\s*\d{2}', text):
            scores[DocumentType.SFR] += 1.5
        
        # ЗАГС
        zags_keywords = ["актовая запись", "загс", "о рождении", "о заключении брака", "о расторжении брака"]
        zags_count = sum(1 for kw in zags_keywords if kw in text)
        if zags_count >= 2:
            scores[DocumentType.ZAGS] += 2.0 + zags_count * 0.5
            details_map[DocumentType.ZAGS]["keywords"] = zags_count
        
        # Наследство
        inheritance_keywords = ["наследство", "наследник", "завещание", "нотариус"]
        inheritance_count = sum(1 for kw in inheritance_keywords if kw in text)
        if inheritance_count >= 2:
            scores[DocumentType.INHERITANCE] += 2.0 + inheritance_count * 0.5
            details_map[DocumentType.INHERITANCE]["keywords"] = inheritance_count
        
        # Отрицательные признаки
        # Если есть явные признаки другого документа, снижаем score
        
        candidates = []
        for doc_type, score in scores.items():
            if score >= 1.0:
                candidates.append(ClassificationCandidate(
                    doc_type=doc_type,
                    score=score,
                    rule_name="weighted_scoring",
                    details=details_map[doc_type]
                ))
        
        return candidates
    
    def _check_ngrams(self, text: str) -> Optional[ClassificationCandidate]:
        """Символьные n-граммы с IDF-взвешиванием"""
        if not self._ngram_idf or not self._document_signatures:
            return None
        
        # Извлекаем n-граммы из текста
        ngrams = self._extract_ngrams(text, n=4)
        
        # Вычисляем similarity с каждым типом документа
        similarities = {}
        for doc_type, signature in self._document_signatures.items():
            common = ngrams & signature
            if common:
                # Взвешиваем по IDF
                weighted_score = sum(self._ngram_idf.get(ng, 0) for ng in common)
                similarities[doc_type] = weighted_score
        
        if similarities:
            best_type = max(similarities, key=similarities.get)
            score = similarities[best_type]
            
            # Нормализуем score
            normalized_score = min(score / 10, 3.0)  # Ограничиваем влияние
            
            return ClassificationCandidate(
                doc_type=best_type,
                score=normalized_score,
                rule_name="ngram_similarity",
                details={"similarity": score}
            )
        
        return None
    
    def _extract_ngrams(self, text: str, n: int = 4) -> Set[str]:
        """Извлечение n-грамм из текста"""
        text = text.replace(' ', '').replace('\n', '')
        return {text[i:i+n] for i in range(len(text) - n + 1)}
    
    def _merge_candidates(self, candidates: List[ClassificationCandidate]) -> List[ClassificationCandidate]:
        """Объединение кандидатов с одинаковым типом"""
        merged_map: Dict[DocumentType, ClassificationCandidate] = {}
        
        for candidate in candidates:
            if candidate.doc_type in merged_map:
                # Суммируем scores, объединяем детали
                existing = merged_map[candidate.doc_type]
                existing.score += candidate.score
                existing.details.update(candidate.details)
                if candidate.rule_name:
                    if "rules" not in existing.details:
                        existing.details["rules"] = []
                    existing.details["rules"].append(candidate.rule_name)
            else:
                merged_map[candidate.doc_type] = candidate
        
        return list(merged_map.values())
    
    def train_ngrams(self, training_data: List[Tuple[str, DocumentType]]):
        """Обучение n-gram модели на размеченных данных"""
        document_ngrams: Dict[DocumentType, List[Set[str]]] = defaultdict(list)
        all_ngrams: Counter = Counter()
        
        # Собираем n-граммы по документам
        for text, doc_type in training_data:
            ngrams = self._extract_ngrams(text, n=4)
            document_ngrams[doc_type].append(ngrams)
            all_ngrams.update(ngrams)
        
        # Вычисляем IDF
        total_docs = len(training_data)
        for ngram, count in all_ngrams.items():
            self._ngram_idf[ngram] = math.log(total_docs / count)
        
        # Создаём сигнатуры типов документов
        for doc_type, ngram_sets in document_ngrams.items():
            # Объединяем все n-граммы данного типа
            signature = set()
            for ng_set in ngram_sets:
                signature.update(ng_set)
            self._document_signatures[doc_type] = signature
        
        logger.info(f"N-gram модель обучена на {total_docs} документах, {len(self._ngram_idf)} уникальных n-грамм")
