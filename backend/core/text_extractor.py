import io
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
import fitz  # PyMuPDF

from backend.models.schemas import TextSource
from backend.config import settings

logger = logging.getLogger(__name__)


class TextExtractor:
    """Извлечение текста и изображений из документов"""
    
    def __init__(self):
        self.pdf_dpi = settings.pdf_render_dpi
        self.max_image_side = settings.max_image_side
        self.jpeg_quality = settings.jpeg_quality
    
    def extract_from_pdf(self, pdf_path: Path) -> List[Tuple[str, bytes, TextSource]]:
        """
        Извлечение текста и изображений из PDF
        
        Returns:
            List[(text, image_bytes, text_source)]
        """
        results = []
        
        try:
            doc = fitz.open(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Извлекаем текстовый слой
                # sort=False для сохранения порядка, совместимого с исходной реализацией
                text = page.get_text(sort=False)
                
                # Рендерим страницу в изображение
                mat = fitz.Matrix(self.pdf_dpi / 72, self.pdf_dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                
                # Конвертируем в PIL Image
                img_data = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_data))
                
                # Подготавливаем изображение
                prepared_image = self._prepare_image(image)
                
                # Сохраняем в JPEG
                img_buffer = io.BytesIO()
                prepared_image.save(img_buffer, format='JPEG', quality=self.jpeg_quality)
                image_bytes = img_buffer.getvalue()
                
                results.append((text, image_bytes, TextSource.TEXT_LAYER))
            
            doc.close()
            
        except Exception as e:
            logger.error(f"Ошибка извлечения из PDF {pdf_path}: {e}")
            raise
        
        return results
    
    def extract_from_image(self, image_path: Path) -> Tuple[bytes, TextSource]:
        """
        Подготовка изображения для OCR
        
        Returns:
            (image_bytes, text_source)
        """
        try:
            image = Image.open(image_path)
            prepared_image = self._prepare_image(image)
            
            img_buffer = io.BytesIO()
            prepared_image.save(img_buffer, format='JPEG', quality=self.jpeg_quality)
            
            return img_buffer.getvalue(), TextSource.LLM_OCR
        
        except Exception as e:
            logger.error(f"Ошибка обработки изображения {image_path}: {e}")
            raise
    
    def extract_from_docx(self, docx_path: Path) -> List[Tuple[str, Optional[bytes]]]:
        """
        Извлечение текста и изображений из DOCX
        
        Returns:
            List[(text, image_bytes or None)]
        """
        try:
            from docx import Document
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import _Cell, Table
            from docx.text.paragraph import Paragraph
            
            doc = Document(docx_path)
            results = []
            text_parts = []
            
            # Извлекаем основной текст
            for element in doc.element.body:
                if isinstance(element, CT_P):
                    paragraph = Paragraph(element, doc)
                    text_parts.append(paragraph.text)
                elif isinstance(element, CT_Tbl):
                    table = Table(element, doc)
                    for row in table.rows:
                        for cell in row.cells:
                            text_parts.append(cell.text)
            
            main_text = "\n".join(text_parts)
            if main_text.strip():
                results.append((main_text, None))
            
            # Извлекаем встроенные изображения
            for rel in doc.part.rels.values():
                if "image" in rel.target_ref:
                    try:
                        image_data = rel.target_part.blob
                        image = Image.open(io.BytesIO(image_data))
                        prepared_image = self._prepare_image(image)
                        
                        img_buffer = io.BytesIO()
                        prepared_image.save(img_buffer, format='JPEG', quality=self.jpeg_quality)
                        
                        results.append(("", img_buffer.getvalue()))
                    except Exception as e:
                        logger.warning(f"Не удалось обработать изображение из DOCX: {e}")
            
            return results
        
        except ImportError:
            logger.error("python-docx не установлен")
            raise Exception("Для обработки DOCX требуется установить python-docx")
        except Exception as e:
            logger.error(f"Ошибка извлечения из DOCX {docx_path}: {e}")
            raise
    
    def _prepare_image(self, image: Image.Image) -> Image.Image:
        """Подготовка изображения для OCR"""
        
        # Применяем EXIF поворот
        try:
            from PIL import ImageOps
            image = ImageOps.exif_transpose(image)
        except Exception:
            pass
        
        # Конвертируем прозрачный фон в белый
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = background
        
        # Приводим к RGB
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Ограничиваем размер
        width, height = image.size
        max_side = max(width, height)
        
        if max_side > self.max_image_side:
            scale = self.max_image_side / max_side
            new_width = int(width * scale)
            new_height = int(height * scale)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return image
    
    def prepare_focused_image(self, image_bytes: bytes) -> bytes:
        """
        Обрезка лишних полей документа (focused режим)
        Простая реализация: обрезаем белые поля
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            
            # Конвертируем в grayscale для анализа
            gray = image.convert('L')
            
            # Находим границы содержимого (инвертируем, так как документ обычно светлый)
            bbox = gray.point(lambda x: 0 if x > 240 else 255).getbbox()
            
            if bbox:
                # Добавляем небольшой отступ
                pad = 20
                x1, y1, x2, y2 = bbox
                x1 = max(0, x1 - pad)
                y1 = max(0, y1 - pad)
                x2 = min(image.width, x2 + pad)
                y2 = min(image.height, y2 + pad)
                
                image = image.crop((x1, y1, x2, y2))
            
            # Сохраняем
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='JPEG', quality=self.jpeg_quality)
            return img_buffer.getvalue()
        
        except Exception as e:
            logger.warning(f"Не удалось обрезать изображение: {e}")
            return image_bytes
    
    def prepare_enhanced_image(self, image_bytes: bytes) -> bytes:
        """
        Улучшение контраста и резкости (enhanced режим)
        """
        try:
            from PIL import ImageEnhance, ImageFilter
            
            image = Image.open(io.BytesIO(image_bytes))
            
            # Увеличиваем контраст
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.3)
            
            # Увеличиваем резкость
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.2)
            
            # Применяем фильтр резкости
            image = image.filter(ImageFilter.SHARPEN)
            
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='JPEG', quality=self.jpeg_quality)
            return img_buffer.getvalue()
        
        except Exception as e:
            logger.warning(f"Не удалось улучшить изображение: {e}")
            return image_bytes
    
    def split_into_tiles(self, image_bytes: bytes) -> Tuple[bytes, bytes]:
        """
        Разделение изображения на верхнюю и нижнюю части с перекрытием
        
        Returns:
            (tile_1_bytes, tile_2_bytes)
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            width, height = image.size
            
            overlap = int(height * settings.ocr_tile_overlap)
            mid = height // 2
            
            # Верхняя часть
            tile_1 = image.crop((0, 0, width, mid + overlap))
            
            # Нижняя часть
            tile_2 = image.crop((0, mid - overlap, width, height))
            
            # Сохраняем
            buffer_1 = io.BytesIO()
            tile_1.save(buffer_1, format='JPEG', quality=self.jpeg_quality)
            
            buffer_2 = io.BytesIO()
            tile_2.save(buffer_2, format='JPEG', quality=self.jpeg_quality)
            
            return buffer_1.getvalue(), buffer_2.getvalue()
        
        except Exception as e:
            logger.error(f"Не удалось разделить изображение: {e}")
            raise
