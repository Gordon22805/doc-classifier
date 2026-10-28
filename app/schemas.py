from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings


class Category(str, Enum):
    PAYMENT = "PAYMENT"
    DELIVERY = "DELIVERY"
    ACCOUNT = "ACCOUNT"
    TECHNICAL = "TECHNICAL"
    REFUND = "REFUND"
    ORDER = "ORDER"
    SUBSCRIPTION = "SUBSCRIPTION"
    OTHER = "OTHER"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


INTENTS_BY_CATEGORY: Dict[Category, List[str]] = {
    Category.PAYMENT: ["DUPLICATE_CHARGE", "FAILED_PAYMENT", "UNKNOWN_CHARGE", "PAYMENT_PENDING"],
    Category.DELIVERY: ["LATE_DELIVERY", "LOST_PACKAGE", "WRONG_ADDRESS", "DELIVERY_STATUS"],
    Category.ACCOUNT: ["PASSWORD_RESET", "ACCOUNT_LOCKED", "LOGIN_PROBLEM", "CHANGE_PERSONAL_DATA"],
    Category.TECHNICAL: ["APP_ERROR", "WEBSITE_ERROR", "FEATURE_NOT_WORKING"],
    Category.REFUND: ["REFUND_REQUEST", "REFUND_PENDING", "REFUND_REJECTED"],
    Category.ORDER: ["CREATE_ORDER", "CANCEL_ORDER", "MODIFY_ORDER", "ORDER_STATUS"],
    Category.SUBSCRIPTION: ["CANCEL_SUBSCRIPTION", "SUBSCRIPTION_PAYMENT", "SUBSCRIPTION_PROBLEM"],
    Category.OTHER: ["OTHER"],
}


class TicketClassification(BaseModel):
    """То, что вернула модель. Отдельно от ответа API: здесь нет department."""

    category: Category
    intent: str
    priority: Priority
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("intent")
    @classmethod
    def intent_not_empty(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("intent пустой")
        return cleaned

    @model_validator(mode="after")
    def intent_matches_category(self) -> "TicketClassification":
        allowed = INTENTS_BY_CATEGORY[self.category]
        if self.intent not in allowed:
            raise ValueError(
                f"intent {self.intent} не относится к категории {self.category.value}. "
                f"Разрешены: {', '.join(allowed)}"
            )
        return self


class TicketRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_must_be_usable(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Текст обращения пуст")
        limit = get_settings().max_text_length
        if len(cleaned) > limit:
            raise ValueError(f"Текст длиннее {limit} символов")
        return cleaned


class PredictionResponse(TicketClassification):
    department: str
