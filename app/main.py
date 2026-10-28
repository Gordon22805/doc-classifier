import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app import analytics
from app.classifier import TicketClassifier
from app.config import get_settings
from app.llm_service import LLMBadResponse, LLMError, LLMNotConfigured, LLMTimeout, LLMService
from app.schemas import PredictionResponse, TicketRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

SAMPLE_TICKETS = Path(__file__).resolve().parent.parent / "data" / "sample_tickets.csv"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.llm_configured:
        logger.info("Groq настроен, модель: %s", settings.llm_model)
    else:
        logger.warning(
            "Groq не настроен: заполните GROQ_API_KEY в .env "
            "(адрес и модель уже заданы по умолчанию)"
        )
    yield


app = FastAPI(
    title="Support Ticket Classifier & Router",
    description=(
        "Классификация обращений в поддержку через LLM и маршрутизация по отделам.\n\n"
        "Откройте POST /predict, вставьте текст обращения и нажмите Execute."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

classifier = TicketClassifier()


@app.get("/health", summary="Проверка работоспособности")
async def health():
    return {"status": "ok"}


@app.post(
    "/predict",
    response_model=PredictionResponse,
    summary="Классифицировать обращение",
    responses={
        422: {"description": "Пустой или слишком длинный текст"},
        503: {"description": "Groq не настроен"},
        504: {"description": "Groq не ответил вовремя"},
        502: {"description": "Ошибка Groq или некорректный ответ модели"},
    },
)
async def predict(ticket: TicketRequest):
    try:
        return await classifier.classify(ticket.text)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except LLMBadResponse as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/analyze",
    summary="Разобрать набор тестовых обращений",
    description=(
        "Берёт обращения из data/sample_tickets.csv, классифицирует каждое "
        "и возвращает распределения. Каждый тикет отправляется в LLM один раз."
    ),
)
async def analyze_tickets(limit: int | None = None):
    settings = get_settings()
    if not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail="Groq не настроен: задайте GROQ_API_KEY в .env "
            "(адрес и модель уже заданы по умолчанию)",
        )

    cap = min(limit or settings.max_tickets, settings.max_tickets)
    try:
        texts: List[str] = analytics.load_sample_tickets(SAMPLE_TICKETS, cap)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Нет файла data/sample_tickets.csv") from exc

    if not texts:
        raise HTTPException(status_code=400, detail="В наборе нет обращений")

    try:
        return await analytics.analyze(texts, classifier)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("Необработанная ошибка на %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервиса"})
