import io
import json
import logging
import zipfile
from pathlib import Path
from typing import List, Dict
from collections import defaultdict
from datetime import datetime

from PIL import Image
import fitz

from backend.models.schemas import PageResult, DocumentType, ProcessingStatus

logger = logging.getLogger(__name__)


class ResultBuilder:
    """Формирование итоговых документов и ZIP-архива"""
    
    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def build_result_archive(
        self,
        job_id: str,
        pages: List[PageResult],
        images_dir: Path
    ) -> Path:
        """
        Создание итогового ZIP-архива
        
        Args:
            job_id: ID задачи
            pages: Результаты обработки страниц
            images_dir: Директория с изображениями страниц
        
        Returns:
            Путь к созданному архиву
        """
        archive_path = self.results_dir / f"{job_id}_result.zip"
        
        # Группируем страницы по типу документа
        grouped = self._group_pages(pages)
        
        # Создаём архив
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            
            for doc_type, type_pages in grouped.items():
                type_name = doc_type.value
                
                # Группируем по источнику
                by_source = self._group_by_source(type_pages)
                
                for source_name, source_pages in by_source.items():
                    # Безопасное имя для папки
                    safe_source = self._safe_filename(source_name)
                    folder_name = f"{type_name}/{safe_source}"
                    
                    # Если страниц несколько, объединяем в PDF
                    if len(source_pages) > 1 and doc_type != DocumentType.UNKNOWN:
                        try:
                            pdf_data = self._merge_to_pdf(source_pages, images_dir)
                            pdf_name = f"{folder_name}/{safe_source}.pdf"
                            zf.writestr(pdf_name, pdf_data)
                        except Exception as e:
                            logger.error(f"Ошибка объединения в PDF: {e}")
                            # Сохраняем отдельными файлами
                            self._add_individual_pages(zf, folder_name, source_pages, images_dir)
                    else:
                        # Сохраняем отдельные страницы
                        self._add_individual_pages(zf, folder_name, source_pages, images_dir)
            
            # Добавляем manifest
            manifest = self._create_manifest(pages)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        
        logger.info(f"Создан архив результатов: {archive_path}")
        return archive_path
    
    def _group_pages(self, pages: List[PageResult]) -> Dict[DocumentType, List[PageResult]]:
        """Группировка страниц по типу документа"""
        grouped: Dict[DocumentType, List[PageResult]] = defaultdict(list)
        
        for page in pages:
            # Используем corrected_type если есть ручная коррекция
            doc_type = page.corrected_type if page.manual_correction else page.doc_type
            grouped[doc_type].append(page)
        
        return grouped
    
    def _group_by_source(self, pages: List[PageResult]) -> Dict[str, List[PageResult]]:
        """Группировка страниц по исходному файлу"""
        by_source: Dict[str, List[PageResult]] = defaultdict(list)
        
        for page in pages:
            by_source[page.source_file].append(page)
        
        # Сортируем страницы внутри каждого источника
        for source in by_source:
            by_source[source] = sorted(by_source[source], key=lambda p: p.page_number)
        
        return by_source
    
    def _resolve_image(self, page: PageResult, images_dir: Path) -> Path:
        """Путь к изображению страницы: абсолютный в image_path или имя файла."""
        raw = Path(page.image_path)
        if raw.is_absolute():
            return raw
        # Относительный путь — только имя файла внутри images_dir
        return images_dir / raw.name

    def _merge_to_pdf(self, pages: List[PageResult], images_dir: Path) -> bytes:
        """Объединение страниц в один PDF"""
        pdf_doc = fitz.open()
        
        for page in pages:
            if page.image_path:
                img_path = self._resolve_image(page, images_dir)
                if img_path.exists():
                    # Открываем изображение
                    img = Image.open(img_path)
                    
                    # Конвертируем в RGB если нужно
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Сохраняем во временный буфер
                    img_buffer = io.BytesIO()
                    img.save(img_buffer, format='JPEG', quality=95)
                    img_bytes = img_buffer.getvalue()
                    
                    # Создаём страницу PDF
                    img_doc = fitz.open(stream=img_bytes, filetype="jpeg")
                    pdf_doc.insert_pdf(img_doc)
                    img_doc.close()
        
        # Сохраняем в байты
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()
        
        return pdf_bytes
    
    def _add_individual_pages(
        self,
        zf: zipfile.ZipFile,
        folder_name: str,
        pages: List[PageResult],
        images_dir: Path
    ):
        """Добавление отдельных страниц в архив"""
        for page in pages:
            if page.image_path:
                img_path = self._resolve_image(page, images_dir)
                if img_path.exists():
                    page_name = f"{folder_name}/page_{page.page_number:03d}{img_path.suffix}"
                    zf.write(img_path, page_name)
    
    def _create_manifest(self, pages: List[PageResult]) -> Dict:
        """
        Создание манифеста без персональных данных
        
        Включает номера страниц, класс, статус и происхождение
        """
        manifest = {
            "created_at": datetime.utcnow().isoformat(),
            "total_pages": len(pages),
            "summary": self._get_summary(pages),
            "pages": []
        }
        
        for page in pages:
            page_info = {
                "page_id": page.page_id,
                "source_file": page.source_file,
                "page_number": page.page_number,
                "doc_type": page.corrected_type.value if page.manual_correction else page.doc_type.value,
                "confidence": round(page.confidence, 2),
                "text_source": page.text_source.value,
                "status": page.status.value,
                "manual_correction": page.manual_correction,
                "diagnostics": {
                    "text_length": page.diagnostics.text_length,
                    "ocr_attempts": page.diagnostics.ocr_attempts,
                    "ocr_profiles_used": page.diagnostics.ocr_profiles_used,
                    "quality_check_passed": page.diagnostics.quality_check_passed,
                    "classification_score": round(page.diagnostics.classification_score, 2) if page.diagnostics.classification_score else None,
                    "score_margin": round(page.diagnostics.score_margin, 2) if page.diagnostics.score_margin else None,
                    "rule_applied": page.diagnostics.rule_applied,
                    "processing_time_ms": round(page.diagnostics.processing_time_ms, 2),
                    "error": page.diagnostics.error
                }
            }
            manifest["pages"].append(page_info)
        
        return manifest
    
    def _get_summary(self, pages: List[PageResult]) -> Dict:
        """Сводная статистика по обработке"""
        by_type = defaultdict(int)
        by_status = defaultdict(int)
        
        for page in pages:
            doc_type = page.corrected_type if page.manual_correction else page.doc_type
            by_type[doc_type.value] += 1
            by_status[page.status.value] += 1
        
        return {
            "by_type": dict(by_type),
            "by_status": dict(by_status)
        }
    
    def _safe_filename(self, filename: str) -> str:
        """Создание безопасного имени файла"""
        # Удаляем или заменяем небезопасные символы
        safe = filename.replace('\\', '_').replace('/', '_')
        safe = safe.replace('..', '_')
        safe = ''.join(c for c in safe if c.isalnum() or c in '._- ')
        safe = safe.strip()
        
        if not safe:
            safe = "unnamed"
        
        # Ограничиваем длину
        if len(safe) > 100:
            safe = safe[:100]
        
        return safe
