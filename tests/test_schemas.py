import pytest

from app.schemas import Category, Priority, Sentiment, TicketClassification


def make(**overrides):
    base = {
        "category": "PAYMENT",
        "intent": "DUPLICATE_CHARGE",
        "priority": "HIGH",
        "sentiment": "NEGATIVE",
        "confidence": 0.93,
    }
    base.update(overrides)
    return base


def test_valid_classification_parsed():
    result = TicketClassification.model_validate(make())

    assert result.category is Category.PAYMENT
    assert result.priority is Priority.HIGH
    assert result.sentiment is Sentiment.NEGATIVE


def test_unknown_category_rejected():
    with pytest.raises(ValueError):
        TicketClassification.model_validate(make(category="BILLING"))


def test_unknown_priority_rejected():
    with pytest.raises(ValueError):
        TicketClassification.model_validate(make(priority="CRITICAL"))


def test_unknown_sentiment_rejected():
    with pytest.raises(ValueError):
        TicketClassification.model_validate(make(sentiment="ANGRY"))


@pytest.mark.parametrize("confidence", [-0.1, 1.5, 93])
def test_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValueError):
        TicketClassification.model_validate(make(confidence=confidence))


def test_intent_from_other_category_rejected():
    with pytest.raises(ValueError, match="не относится к категории"):
        TicketClassification.model_validate(make(category="DELIVERY", intent="DUPLICATE_CHARGE"))


def test_intent_normalized_to_upper():
    result = TicketClassification.model_validate(make(intent="duplicate_charge"))

    assert result.intent == "DUPLICATE_CHARGE"


def test_other_category_accepts_only_other_intent():
    assert TicketClassification.model_validate(
        make(category="OTHER", intent="OTHER")
    ).intent == "OTHER"

    with pytest.raises(ValueError):
        TicketClassification.model_validate(make(category="OTHER", intent="DUPLICATE_CHARGE"))
