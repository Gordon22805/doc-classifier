import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm_service import LLMBadResponse, LLMNotConfigured, LLMTimeout
from app.main import app, classifier
from app.schemas import TicketClassification

VALID = TicketClassification(
    category="PAYMENT",
    intent="DUPLICATE_CHARGE",
    priority="HIGH",
    sentiment="NEGATIVE",
    confidence=0.93,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_predict_returns_department_from_routing(client, monkeypatch):
    async def fake(text):
        return VALID

    monkeypatch.setattr(classifier.llm, "classify", fake)
    response = client.post("/predict", json={"text": "С меня дважды списали деньги"})

    assert response.status_code == 200
    assert response.json() == {
        "category": "PAYMENT",
        "intent": "DUPLICATE_CHARGE",
        "priority": "HIGH",
        "sentiment": "NEGATIVE",
        "confidence": 0.93,
        "department": "BILLING",
    }


def test_empty_text_rejected(client):
    assert client.post("/predict", json={"text": "   "}).status_code == 422


def test_missing_text_rejected(client):
    assert client.post("/predict", json={}).status_code == 422


def test_too_long_text_rejected(client):
    assert client.post("/predict", json={"text": "а" * 5000}).status_code == 422


def test_not_configured_maps_to_503(client, monkeypatch):
    async def fake(text):
        raise LLMNotConfigured("нет ключа")

    monkeypatch.setattr(classifier.llm, "classify", fake)

    assert client.post("/predict", json={"text": "тест"}).status_code == 503


def test_timeout_maps_to_504(client, monkeypatch):
    async def fake(text):
        raise LLMTimeout("долго")

    monkeypatch.setattr(classifier.llm, "classify", fake)

    assert client.post("/predict", json={"text": "тест"}).status_code == 504


def test_bad_model_output_maps_to_502(client, monkeypatch):
    async def fake(text):
        raise LLMBadResponse("не JSON")

    monkeypatch.setattr(classifier.llm, "classify", fake)

    assert client.post("/predict", json={"text": "тест"}).status_code == 502


def test_analyze_without_configuration_is_503(client, monkeypatch):
    monkeypatch.setattr(classifier.llm, "is_configured", lambda: False)

    assert client.post("/analyze").status_code == 503
