import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from backend.models.schemas import (
    PageResult,
    PageDiagnostics,
    DocumentType,
    TextSource,
    ProcessingStatus,
    OCRProfile
)
from backend.core.text_extractor import TextExtractor
from backend.core.text_quality import TextQualityChecker
from backend.core.text_normalizer import TextNormalizer
from backend.core.ocr_client import OCRClient
from backend.core.classifier import DocumentClassifier
from backend.core.context_classifier import ContextClassifier
from backend.core.result_builder import ResultBuilder
from backend.utils.archive_handler import ArchiveHandler
from backend.config import settings

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Основной процессор документов - координирует весь конвейер"""
    
    def __init__(self, temp_dir: Path):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.extractor = TextExtractor()
        self.quality_checker = TextQualityChecker()
        self.normalizer = TextNormalizer()
        self.ocr_client = OCRClient()
        self.classifier = DocumentClassifier()
        self.context_classifier = ContextClassifier()
        self.archive_handler = ArchiveHandler()
        self.result_builder = ResultBuilder(Path(settings.results_dir))
        
        self.ocr_semaphore = asyncio.Semaphore(settings.ocr_global_concurrency)
    
    async def process_files(self, file_paths: List[Path], job_id: str) -> List[PageResult]:
        """
        Обработка списка файлов
        
        Args:
            file_paths: Пути к файлам для обработки
            job_id: ID задачи
        
        Returns:
            Список результатов обработки страниц
        """
        all_pages = []
        
        for file_path in file_paths:
            try:
                pages = await self.process_file(file_path, job_id)
                all_pages.extend(pages)
            except Exception as e:
                logger.error(f"Ошибка обработки файла {file_path}: {e}")
                # Создаём запись об ошибке
                error_page = self._create_error_page(file_path, str(e))
                all_pages.append(error_page)
        
        # Применяем контекстную классификацию
        all_pages = self.context_classifier.apply_context(all_pages)
        
        return all_pages
    
    async def process_file(self, file_path: Path, job_id: str) -> List[PageResult]:
        """Обработка одного файла"""
        suffix = file_path.suffix.lower()
        
        if suffix == '.pdf':
            return await self._process_pdf(file_path, job_id)
        elif suffix in {'.jpg', '.jpeg', '.png', '.heic'}:
            return await self._process_image(file_path, job_id)
        elif suffix == '.docx':
            return await self._process_docx(file_path, job_id)
        elif suffix in {'.zip', '.7z'}:
            return await self._process_archive(file_path, job_id)
        else:
            raise Exception(f"Неподдерживаемый формат: {suffix}")
    
    async def _process_pdf(self, pdf_path: Path, job_id: str) -> List[PageResult]:
        """Обработка PDF файла"""
        logger.info(f"Обработка PDF: {pdf_path.name}")
        
        pages_data = self.extractor.extract_from_pdf(pdf_path)
        results = []
        
        for page_num, (text, image_bytes, text_source) in enumerate(pages_data, start=1):
            page_id = f"{job_id}_page_{uuid.uuid4().hex[:8]}"
            start_time = time.time()
            
            # Сохраняем изображение страницы
            image_path = self._save_page_image(job_id, page_id, image_bytes)
            
            # Проверка качества текста
            quality = self.quality_checker.check_quality(text)
            needs_ocr = not quality.is_good
            ocr_unavailable = needs_ocr and not self.ocr_client.is_available()
            
            # Если качество плохое, запускаем OCR
            if needs_ocr and self.ocr_client.is_available():
                text, ocr_diagnostics = await self._run_ocr_cascade(
                    image_bytes,
                    text  # Добавляем к существующему тексту
                )
                text_source = TextSource.LLM_OCR
            else:
                ocr_diagnostics = {
                    "attempts": 0,
                    "profiles": []
                }
            
            # Нормализация текста
            normalized_text = self.normalizer.normalize(text)
            
            # Классификация
            doc_type, confidence, candidates = self.classifier.classify(
                normalized_text,
                filename=pdf_path.name
            )
            
            # Диагностика
            processing_time = (time.time() - start_time) * 1000
            
            diagnostics = PageDiagnostics(
                source_file=pdf_path.name,
                page_number=page_num,
                text_source=text_source,
                text_length=len(text),
                ocr_attempts=ocr_diagnostics["attempts"],
                ocr_profiles_used=ocr_diagnostics["profiles"],
                quality_check_passed=quality.is_good,
                quality_issues=quality.issues,
                classification_score=confidence,
                score_margin=candidates[1].score if len(candidates) > 1 else 0,
                rule_applied=candidates[0].rule_name if candidates else None,
                top_candidates=candidates[:3],
                processing_time_ms=processing_time,
                error=(
                    "Нет текстового слоя, а OCR не настроен: задайте OPENAI_API_KEY в .env"
                    if ocr_unavailable else None
                )
            )
            
            result = PageResult(
                page_id=page_id,
                source_file=pdf_path.name,
                page_number=page_num,
                doc_type=doc_type,
                confidence=confidence,
                text_source=text_source,
                status=ProcessingStatus.ERROR if ocr_unavailable else ProcessingStatus.SUCCESS,
                image_path=str(image_path),
                diagnostics=diagnostics
            )
            
            results.append(result)
        
        logger.info(f"Обработано {len(results)} страниц из {pdf_path.name}")
        return results
    
    async def _process_image(self, image_path: Path, job_id: str) -> List[PageResult]:
        """Обработка изображения"""
        logger.info(f"Обработка изображения: {image_path.name}")
        
        page_id = f"{job_id}_page_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        
        # Подготовка изображения
        image_bytes, _ = self.extractor.extract_from_image(image_path)
        
        # Сохраняем
        saved_path = self._save_page_image(job_id, page_id, image_bytes)
        
        # OCR
        text = ""
        ocr_diagnostics = {"attempts": 0, "profiles": []}
        ocr_available = self.ocr_client.is_available()
        
        if ocr_available:
            text, ocr_diagnostics = await self._run_ocr_cascade(image_bytes, "")
        
        # Нормализация и классификация
        normalized_text = self.normalizer.normalize(text)
        doc_type, confidence, candidates = self.classifier.classify(
            normalized_text,
            filename=image_path.name
        )
        
        processing_time = (time.time() - start_time) * 1000
        
        diagnostics = PageDiagnostics(
            source_file=image_path.name,
            page_number=1,
            text_source=TextSource.LLM_OCR,
            text_length=len(text),
            ocr_attempts=ocr_diagnostics["attempts"],
            ocr_profiles_used=ocr_diagnostics["profiles"],
            quality_check_passed=bool(text.strip()),
            classification_score=confidence,
            score_margin=candidates[1].score if len(candidates) > 1 else 0,
            rule_applied=candidates[0].rule_name if candidates else None,
            top_candidates=candidates[:3],
            processing_time_ms=processing_time,
            error=None if ocr_available else
            "Для изображений нужен OCR: задайте OPENAI_API_KEY в .env"
        )
        
        result = PageResult(
            page_id=page_id,
            source_file=image_path.name,
            page_number=1,
            doc_type=doc_type,
            confidence=confidence,
            text_source=TextSource.LLM_OCR,
            status=ProcessingStatus.SUCCESS if ocr_available else ProcessingStatus.ERROR,
            image_path=str(saved_path),
            diagnostics=diagnostics
        )
        
        return [result]
    
    async def _process_docx(self, docx_path: Path, job_id: str) -> List[PageResult]:
        """Обработка DOCX"""
        logger.info(f"Обработка DOCX: {docx_path.name}")
        
        extracts = self.extractor.extract_from_docx(docx_path)
        results = []
        
        for page_num, (text, image_bytes) in enumerate(extracts, start=1):
            page_id = f"{job_id}_page_{uuid.uuid4().hex[:8]}"
            start_time = time.time()
            
            # Если есть изображение, обрабатываем его через OCR
            if image_bytes:
                saved_path = self._save_page_image(job_id, page_id, image_bytes)
                
                if self.ocr_client.is_available():
                    ocr_text, ocr_diag = await self._run_ocr_cascade(image_bytes, "")
                    text += "\n" + ocr_text
                    text_source = TextSource.LLM_OCR
                else:
                    text_source = TextSource.DOCX
                    ocr_diag = {"attempts": 0, "profiles": []}
            else:
                saved_path = None
                text_source = TextSource.DOCX
                ocr_diag = {"attempts": 0, "profiles": []}
            
            # Нормализация и классификация
            normalized_text = self.normalizer.normalize(text)
            doc_type, confidence, candidates = self.classifier.classify(
                normalized_text,
                filename=docx_path.name
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            diagnostics = PageDiagnostics(
                source_file=docx_path.name,
                page_number=page_num,
                text_source=text_source,
                text_length=len(text),
                ocr_attempts=ocr_diag["attempts"],
                ocr_profiles_used=ocr_diag["profiles"],
                quality_check_passed=True,
                classification_score=confidence,
                score_margin=candidates[1].score if len(candidates) > 1 else 0,
                rule_applied=candidates[0].rule_name if candidates else None,
                top_candidates=candidates[:3],
                processing_time_ms=processing_time
            )
            
            result = PageResult(
                page_id=page_id,
                source_file=docx_path.name,
                page_number=page_num,
                doc_type=doc_type,
                confidence=confidence,
                text_source=text_source,
                status=ProcessingStatus.SUCCESS,
                image_path=str(saved_path) if saved_path else None,
                diagnostics=diagnostics
            )
            
            results.append(result)
        
        return results
    
    async def _process_archive(self, archive_path: Path, job_id: str) -> List[PageResult]:
        """Обработка архива"""
        logger.info(f"Обработка архива: {archive_path.name}")
        
        # Извлекаем
        extract_dir = self.temp_dir / job_id / "extracted" / archive_path.stem
        extracted_files = self.archive_handler.extract_archive(archive_path, extract_dir)
        
        # Удаляем дубликаты
        unique_files = self.archive_handler.remove_duplicates(extracted_files)
        
        # Обрабатываем каждый файл
        all_results = []
        for file_path in unique_files:
            try:
                results = await self.process_file(file_path, job_id)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Ошибка обработки файла из архива {file_path}: {e}")
        
        return all_results
    
    def _save_page_image(self, job_id: str, page_id: str, image_bytes: bytes) -> Path:
        """Сохранение изображения страницы"""
        images_dir = self.temp_dir / job_id / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        
        image_path = images_dir / f"{page_id}.jpg"
        with open(image_path, 'wb') as f:
            f.write(image_bytes)
        
        return image_path
    
    def _create_error_page(self, file_path: Path, error: str) -> PageResult:
        """Создание записи об ошибке обработки"""
        return PageResult(
            page_id=f"error_{uuid.uuid4().hex[:8]}",
            source_file=file_path.name,
            page_number=0,
            doc_type=DocumentType.UNKNOWN,
            confidence=0,
            text_source=TextSource.TEXT_LAYER,
            status=ProcessingStatus.ERROR,
            diagnostics=PageDiagnostics(
                source_file=file_path.name,
                page_number=0,
                text_source=TextSource.TEXT_LAYER,
                text_length=0,
                error=error
            )
        )
    
    async def _run_ocr_cascade(
        self,
        original_image: bytes,
        existing_text: str
    ) -> Tuple[str, dict]:
        """
        Каскадный OCR с несколькими стратегиями
        
        Args:
            original_image: Исходное изображение
            existing_text: Уже извлечённый текст (из текстового слоя)
        
        Returns:
            (combined_text, diagnostics)
        """
        if not self.ocr_client.is_available():
            return existing_text, {"attempts": 0, "profiles": []}
        
        attempts = 0
        profiles_used = []
        all_texts = [existing_text] if existing_text.strip() else []
        combined_text = existing_text
        
        # Стратегия 1: original
        try:
            async with self.ocr_semaphore:
                attempts += 1
                profiles_used.append(OCRProfile.ORIGINAL.value)
                
                response = await self.ocr_client.recognize(
                    original_image,
                    profile=OCRProfile.ORIGINAL
                )
                
                if response.text:
                    all_texts.append(response.text)
                    combined_text = self._merge_texts(all_texts)
                    
                    # Проверяем, достаточно ли хорош результат
                    quality = self.quality_checker.check_quality(
                        response.text,
                        is_ocr=True,
                        ocr_confidence=response.confidence
                    )
                    
                    if quality.is_good and quality.score >= 70:
                        # Достаточно хорошо, останавливаемся
                        return combined_text, {
                            "attempts": attempts,
                            "profiles": profiles_used
                        }
        
        except Exception as e:
            logger.error(f"OCR original failed: {e}")
        
        # Если не включены дополнительные попытки, останавливаемся
        if not settings.ocr_tiled_retry_enabled:
            return combined_text, {"attempts": attempts, "profiles": profiles_used}
        
        # Стратегия 2: focused
        try:
            focused_image = self.extractor.prepare_focused_image(original_image)
            
            async with self.ocr_semaphore:
                attempts += 1
                profiles_used.append(OCRProfile.FOCUSED.value)
                
                response = await self.ocr_client.recognize(
                    focused_image,
                    profile=OCRProfile.FOCUSED
                )
                
                if response.text:
                    all_texts.append(response.text)
                    combined_text = self._merge_texts(all_texts)
                    
                    # Проверяем улучшение
                    if self._check_improvement(combined_text, existing_text):
                        return combined_text, {
                            "attempts": attempts,
                            "profiles": profiles_used
                        }
        
        except Exception as e:
            logger.error(f"OCR focused failed: {e}")
        
        # Стратегия 3: enhanced
        try:
            enhanced_image = self.extractor.prepare_enhanced_image(focused_image if 'focused_image' in locals() else original_image)
            
            async with self.ocr_semaphore:
                attempts += 1
                profiles_used.append(OCRProfile.ENHANCED.value)
                
                response = await self.ocr_client.recognize(
                    enhanced_image,
                    profile=OCRProfile.ENHANCED
                )
                
                if response.text:
                    all_texts.append(response.text)
                    combined_text = self._merge_texts(all_texts)
                    
                    if self._check_improvement(combined_text, existing_text):
                        return combined_text, {
                            "attempts": attempts,
                            "profiles": profiles_used
                        }
        
        except Exception as e:
            logger.error(f"OCR enhanced failed: {e}")
        
        # Стратегия 4: tiled (верх и низ отдельно)
        try:
            tile_1, tile_2 = self.extractor.split_into_tiles(
                enhanced_image if 'enhanced_image' in locals() else original_image
            )
            
            # Обрабатываем тайлы параллельно с ограничением
            tile_tasks = [
                self._ocr_tile(tile_1, OCRProfile.TILE),
                self._ocr_tile(tile_2, OCRProfile.TILE)
            ]
            
            tile_results = await asyncio.gather(*tile_tasks, return_exceptions=True)
            
            for tile_text in tile_results:
                if isinstance(tile_text, str) and tile_text:
                    all_texts.append(tile_text)
                    attempts += 1
            
            profiles_used.append(f"{OCRProfile.TILE.value}_1")
            profiles_used.append(f"{OCRProfile.TILE.value}_2")
            
            combined_text = self._merge_texts(all_texts)
        
        except Exception as e:
            logger.error(f"OCR tiled failed: {e}")
        
        return combined_text, {
            "attempts": attempts,
            "profiles": profiles_used
        }
    
    async def _ocr_tile(self, tile_image: bytes, profile: OCRProfile) -> str:
        """OCR одного тайла"""
        async with self.ocr_semaphore:
            response = await self.ocr_client.recognize(tile_image, profile=profile)
            return response.text
    
    def _merge_texts(self, texts: List[str]) -> str:
        """
        Объединение текстов из разных OCR-проходов
        
        Не увеличиваем вес за счёт повторений
        """
        if not texts:
            return ""
        
        unique_lines = []
        seen = set()
        
        for text in texts:
            for line in text.split('\n'):
                line = line.strip()
                if line and line not in seen:
                    unique_lines.append(line)
                    seen.add(line)
        
        return '\n'.join(unique_lines)
    
    def _check_improvement(self, new_text: str, old_text: str) -> bool:
        """Проверка, улучшился ли текст после OCR"""
        if not old_text:
            return bool(new_text)
        
        new_quality = self.quality_checker.check_quality(new_text)
        old_quality = self.quality_checker.check_quality(old_text)
        
        # Улучшение, если новый score существенно выше
        return new_quality.score > old_quality.score + 20
