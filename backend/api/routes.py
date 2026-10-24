import logging
import uuid
from pathlib import Path
from typing import List
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from backend.models.schemas import JobStatus, ProcessingStatus, PageResult, DocumentType
from backend.core.document_processor import DocumentProcessor
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Хранилище задач (в реальном приложении использовать Redis или БД)
jobs_storage = {}

# Процессор документов
processor = DocumentProcessor(Path(settings.temp_dir))


@router.get("/health")
async def health_check():
    """
    Health check endpoint для мониторинга
    
    Возвращает статус сервиса и доступность OCR
    """
    from backend.core.ocr_client import OCRClient
    
    ocr_client = OCRClient()
    ocr_available = ocr_client.is_available()
    
    return {
        "status": "healthy",
        "ocr_service": "available" if ocr_available else "unavailable",
        "vision_model": settings.vision_model,
        "vision_base_url": settings.vision_base_url or "api.openai.com",
        "api_key_configured": bool(settings.openai_api_key)
    }


@router.post("/upload", response_model=JobStatus)
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Загрузка файлов для обработки
    
    Принимает один или несколько файлов и запускает обработку
    """
    if not files:
        raise HTTPException(status_code=400, detail="Не загружены файлы")
    
    # Создаём задачу
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow().isoformat()
    
    job_status = JobStatus(
        job_id=job_id,
        status=ProcessingStatus.PENDING,
        total_files=len(files),
        created_at=timestamp,
        updated_at=timestamp
    )
    
    jobs_storage[job_id] = job_status
    
    # Сохраняем загруженные файлы
    upload_dir = Path(settings.upload_dir) / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_paths = []
    for upload_file in files:
        file_path = upload_dir / upload_file.filename
        
        # Сохраняем файл
        content = await upload_file.read()
        with open(file_path, 'wb') as f:
            f.write(content)
        
        file_paths.append(file_path)
    
    # Запускаем обработку асинхронно
    import asyncio
    asyncio.create_task(process_job(job_id, file_paths))
    
    job_status.status = ProcessingStatus.PROCESSING
    job_status.updated_at = datetime.utcnow().isoformat()
    
    return job_status


async def process_job(job_id: str, file_paths: List[Path]):
    """Фоновая обработка задачи"""
    try:
        job_status = jobs_storage[job_id]
        job_status.status = ProcessingStatus.PROCESSING
        job_status.updated_at = datetime.utcnow().isoformat()
        
        # Обрабатываем файлы
        pages = await processor.process_files(file_paths, job_id)
        
        job_status.pages = pages
        job_status.total_pages = len(pages)
        job_status.processed_pages = len(pages)
        
        # Формируем результат
        images_dir = Path(settings.temp_dir) / job_id / "images"
        result_zip = processor.result_builder.build_result_archive(
            job_id,
            pages,
            images_dir
        )
        
        job_status.result_zip_path = str(result_zip)
        
        # Проверяем, есть ли ошибки
        has_errors = any(p.status == ProcessingStatus.ERROR for p in pages)
        has_success = any(p.status == ProcessingStatus.SUCCESS for p in pages)
        
        if has_errors and has_success:
            job_status.status = ProcessingStatus.PARTIAL_ERROR
        elif has_errors:
            job_status.status = ProcessingStatus.ERROR
        else:
            job_status.status = ProcessingStatus.SUCCESS
        
        job_status.updated_at = datetime.utcnow().isoformat()
        
        logger.info(f"Задача {job_id} завершена: {job_status.status}")
    
    except Exception as e:
        logger.error(f"Ошибка обработки задачи {job_id}: {e}")
        job_status = jobs_storage[job_id]
        job_status.status = ProcessingStatus.ERROR
        job_status.error = str(e)
        job_status.updated_at = datetime.utcnow().isoformat()


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Получение статуса задачи"""
    if job_id not in jobs_storage:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    return jobs_storage[job_id]


@router.post("/correct/{job_id}/{page_id}")
async def correct_page(job_id: str, page_id: str, doc_type: str):
    """
    Ручная коррекция типа документа страницы
    
    Args:
        job_id: ID задачи
        page_id: ID страницы
        doc_type: Новый тип документа (значение из DocumentType)
    """
    if job_id not in jobs_storage:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    job_status = jobs_storage[job_id]
    
    # Находим страницу
    page = next((p for p in job_status.pages if p.page_id == page_id), None)
    if not page:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    
    # Применяем коррекцию
    try:
        new_type = DocumentType(doc_type)
        page.manual_correction = True
        page.corrected_type = new_type
        
        job_status.updated_at = datetime.utcnow().isoformat()
        
        logger.info(f"Исправлен тип страницы {page_id}: {page.doc_type} -> {new_type}")
        
        return {"success": True, "page_id": page_id, "new_type": doc_type}
    
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип документа: {doc_type}")


@router.post("/rebuild/{job_id}")
async def rebuild_result(job_id: str):
    """
    Повторное формирование результата с учётом ручных исправлений
    """
    if job_id not in jobs_storage:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    job_status = jobs_storage[job_id]
    
    try:
        images_dir = Path(settings.temp_dir) / job_id / "images"
        result_zip = processor.result_builder.build_result_archive(
            job_id,
            job_status.pages,
            images_dir
        )
        
        job_status.result_zip_path = str(result_zip)
        job_status.updated_at = datetime.utcnow().isoformat()
        
        return {"success": True, "result_path": str(result_zip)}
    
    except Exception as e:
        logger.error(f"Ошибка перестроения результата {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Скачивание ZIP-архива с результатами"""
    if job_id not in jobs_storage:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    job_status = jobs_storage[job_id]
    
    if not job_status.result_zip_path:
        raise HTTPException(status_code=404, detail="Результат ещё не готов")
    
    result_path = Path(job_status.result_zip_path)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден")
    
    return FileResponse(
        result_path,
        media_type="application/zip",
        filename=f"{job_id}_result.zip"
    )


@router.get("/image/{job_id}/{page_id}")
async def get_page_image(job_id: str, page_id: str):
    """Получение изображения страницы для предпросмотра"""
    if job_id not in jobs_storage:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    job_status = jobs_storage[job_id]
    page = next((p for p in job_status.pages if p.page_id == page_id), None)
    
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    
    # image_path — либо абсолютный путь, либо имя файла внутри images_dir
    raw = Path(page.image_path)
    if raw.is_absolute():
        image_path = raw
    else:
        image_path = Path(settings.temp_dir) / job_id / "images" / raw.name
    
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Файл изображения не найден")
    
    return FileResponse(image_path, media_type="image/jpeg")
