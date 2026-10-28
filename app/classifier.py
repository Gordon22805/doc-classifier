import logging
import time

from app.llm_service import LLMService
from app.routing import get_department
from app.schemas import PredictionResponse, TicketClassification

logger = logging.getLogger(__name__)


class TicketClassifier:
    """LLM выдаёт категорию и признаки, department добавляет Python."""

    def __init__(self, llm_service: LLMService | None = None):
        self.llm = llm_service or LLMService()

    async def classify(self, text: str) -> PredictionResponse:
        started = time.perf_counter()
        result: TicketClassification = await self.llm.classify(text)

        response = PredictionResponse(
            **result.model_dump(),
            department=get_department(result.category.value),
        )
        logger.info(
            "Классифицировано: %s/%s, %.2f с",
            response.category.value,
            response.intent,
            time.perf_counter() - started,
        )
        return response
