import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Создание директорий
Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.results_dir).mkdir(parents=True, exist_ok=True)

# Создание приложения
app = FastAPI(
    title="OCR и Классификация Документов",
    description="AI-сервис для распознавания и классификации документов",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router, prefix="/api", tags=["documents"])

# Статические файлы (фронтенд)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


@app.on_event("startup")
async def startup_event():
    logger.info("Запуск OCR Classification Service")
    logger.info(f"OpenAI API ключ: {'настроен' if settings.openai_api_key else 'не настроен'}")
    logger.info(f"Vision модель: {settings.vision_model}")
    logger.info(f"Рабочая директория: {settings.temp_dir}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Остановка OCR Classification Service")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
