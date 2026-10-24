import logging
from typing import List, Dict, Optional
from collections import Counter

from backend.models.schemas import DocumentType, PageResult, ProcessingStatus

logger = logging.getLogger(__name__)


class ContextClassifier:
    """Осторожное применение контекста многостраничных документов"""
    
    def __init__(self):
        # Типы, которые могут быть многостраничными
        self.multipage_types = {
            DocumentType.EGRN,
            DocumentType.DKP,
            DocumentType.PDKP,
            DocumentType.DDU,
            DocumentType.ACCOUNTING,
            DocumentType.INHERITANCE,
            DocumentType.SFR
        }
    
    def apply_context(self, pages: List[PageResult]) -> List[PageResult]:
        """
        Применение контекстных правил к страницам одного источника
        
        Args:
            pages: Список результатов страниц, уже классифицированных индивидуально
        
        Returns:
            Обновлённый список с учётом контекста
        """
        if len(pages) <= 1:
            return pages
        
        # Группируем по source_file
        by_source: Dict[str, List[PageResult]] = {}
        for page in pages:
            source = page.source_file
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(page)
        
        # Применяем контекст для каждого источника
        updated_pages = []
        for source, source_pages in by_source.items():
            source_pages = sorted(source_pages, key=lambda p: p.page_number)
            updated = self._apply_source_context(source_pages)
            updated_pages.extend(updated)
        
        return updated_pages
    
    def _apply_source_context(self, pages: List[PageResult]) -> List[PageResult]:
        """Применение контекста к страницам одного файла"""
        
        # Находим уверенные классификации
        confident_pages = [
            p for p in pages
            if p.doc_type != DocumentType.UNKNOWN
            and p.confidence >= 2.0
            and p.status == ProcessingStatus.SUCCESS
        ]
        
        if not confident_pages:
            return pages
        
        # Подсчитываем типы
        type_counts = Counter(p.doc_type for p in confident_pages)
        
        # Если есть доминирующий тип (минимум 2 страницы)
        if type_counts.most_common(1)[0][1] >= 2:
            dominant_type = type_counts.most_common(1)[0][0]
            
            # Проверяем, является ли это многостраничным типом
            if dominant_type in self.multipage_types:
                pages = self._inherit_type(pages, dominant_type)
        
        # Специальная обработка для ЕГРН
        pages = self._apply_egrn_continuation(pages)
        
        return pages
    
    def _inherit_type(self, pages: List[PageResult], anchor_type: DocumentType) -> List[PageResult]:
        """
        Осторожное наследование типа
        
        Продолжение может наследовать класс только при отсутствии
        уверенного противоречащего результата
        """
        # Находим первую уверенную страницу нужного типа
        anchor_idx = None
        for i, page in enumerate(pages):
            if page.doc_type == anchor_type and page.confidence >= 2.0:
                anchor_idx = i
                break
        
        if anchor_idx is None:
            return pages
        
        updated_pages = list(pages)
        
        # Смотрим на следующие страницы
        for i in range(anchor_idx + 1, len(pages)):
            page = updated_pages[i]
            
            # Наследуем только если:
            # 1. Страница не распознана (UNKNOWN)
            # 2. ИЛИ confidence низкая (< 2.0) и нет явного конфликта
            if page.doc_type == DocumentType.UNKNOWN:
                # Безопасно наследуем
                updated_pages[i] = self._update_page_type(
                    page,
                    anchor_type,
                    reason="inherited_from_anchor",
                    confidence=1.5  # Пониженная уверенность
                )
            
            elif page.confidence < 2.0 and page.doc_type != anchor_type:
                # Есть слабое предположение о другом типе
                # Не перезаписываем автоматически
                pass
            
            elif page.doc_type == anchor_type:
                # Та же классификация, ок
                continue
            
            else:
                # Уверенная классификация другого типа - НЕ ТРОГАЕМ
                # Возможно, это начало нового документа в том же файле
                break
        
        return updated_pages
    
    def _apply_egrn_continuation(self, pages: List[PageResult]) -> List[PageResult]:
        """
        Специальная проверка продолжений ЕГРН
        
        Для ЕГРН проверяем реестровые и кадастровые признаки
        на продолжениях, таблицах и планах
        """
        egrn_pages = [p for p in pages if p.doc_type == DocumentType.EGRN]
        
        if not egrn_pages:
            return pages
        
        updated_pages = list(pages)
        
        # Ищем страницы с признаками ЕГРН-продолжений
        for i, page in enumerate(pages):
            if page.doc_type == DocumentType.UNKNOWN:
                # Проверяем текст на признаки ЕГРН
                # (в реальности нужен доступ к тексту, здесь упрощение)
                # Если есть кадастровые номера или таблицы с характеристиками
                pass
        
        return updated_pages
    
    def _update_page_type(
        self,
        page: PageResult,
        new_type: DocumentType,
        reason: str,
        confidence: float
    ) -> PageResult:
        """Обновление типа страницы с сохранением диагностики"""
        page.doc_type = new_type
        page.confidence = confidence
        page.diagnostics.rule_applied = reason
        return page
