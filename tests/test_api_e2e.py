"""Сквозной тест API: загрузка → статус → коррекция → пересборка → скачивание."""
import io
import json
import zipfile

import fitz
import pytest
from fastapi.testclient import TestClient

from backend.models.schemas import OCRResponse


def _make_scan_pdf() -> bytes:
    """PDF из трёх страниц-картинок без текстового слоя."""
    src = fitz.open()
    for lines in (
        ["РОССИЙСКАЯ ФЕДЕРАЦИЯ", "ПАСПОРТ", "Серия 45 00 Номер 123456"],
        ["ВЫПИСКА ИЗ ЕГРН", "Кадастровый номер 77:01:0001001:1234"],
        ["ПЛАТЕЖНОЕ ПОРУЧЕНИЕ N 42", "Форма 0401060"],
    ):
        page = src.new_page(width=595, height=842)
        for i, line in enumerate(lines):
            page.insert_text((60, 100 + i * 30), line, fontsize=14, fontname="helv")

    out = fitz.open()
    for page in src:
        new_page = out.new_page(width=595, height=842)
        new_page.insert_image(new_page.rect, stream=page.get_pixmap(dpi=120).tobytes("png"))
    data = out.tobytes()
    out.close()
    src.close()
    return data


TEXTS_BY_CALL = [
    "РОССИЙСКАЯ ФЕДЕРАЦИЯ\nПАСПОРТ\nСерия 45 00 Номер 123456",
    "ВЫПИСКА ИЗ ЕГРН\nКадастровый номер 77:01:0001001:1234",
    "ПЛАТЕЖНОЕ ПОРУЧЕНИЕ N 42\nФорма 0401060",
]


@pytest.fixture
def client(monkeypatch, tmp_path):
    from backend.config import settings
    from backend.core.ocr_client import OCRClient

    # Изолируем файловые директории теста
    monkeypatch.setattr(settings, "temp_dir", str(tmp_path / "temp"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "results_dir", str(tmp_path / "results"))
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    calls = {"n": 0}

    async def fake_recognize(self, image_data, profile=None, use_unwarping=False):
        text = TEXTS_BY_CALL[calls["n"] % len(TEXTS_BY_CALL)]
        calls["n"] += 1
        return OCRResponse(text=text, confidence=0.95, method="fake_vision")

    monkeypatch.setattr(OCRClient, "recognize", fake_recognize)

    # Пересоздаём приложение с актуальными настройками
    import importlib
    import backend.api.routes as routes
    import backend.main as main_module

    importlib.reload(routes)
    routes.processor.temp_dir = tmp_path / "temp"
    routes.processor.result_builder.results_dir = tmp_path / "results"
    routes.processor.result_builder.results_dir.mkdir(parents=True, exist_ok=True)

    return TestClient(main_module.app)


def test_full_job_flow(client):
    pdf = _make_scan_pdf()
    resp = client.post(
        "/api/upload",
        files=[("files", ("scan.pdf", io.BytesIO(pdf), "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # Фоновая задача: TestClient выполняет create_task в том же цикле
    status = None
    for _ in range(50):
        r = client.get(f"/api/status/{job_id}")
        assert r.status_code == 200
        status = r.json()
        if status["status"] not in ("pending", "processing"):
            break

    assert status["status"] == "success", status
    assert status["total_pages"] == 3
    pages = status["pages"]
    assert len(pages) == 3
    assert all(p["text_source"] == "llm_ocr" for p in pages), pages

    # Изображение страницы доступно (проверка фикса пути)
    page0 = pages[0]
    img = client.get(f"/api/image/{job_id}/{page0['page_id']}")
    assert img.status_code == 200, img.text
    assert img.headers["content-type"] == "image/jpeg"
    assert len(img.content) > 1000

    # Ручная коррекция первой страницы в другой тип
    target = "accounting"
    r = client.post(f"/api/correct/{job_id}/{page0['page_id']}?doc_type={target}")
    assert r.status_code == 200, r.text
    assert r.json()["new_type"] == target

    # Пересборка с учётом коррекции
    r = client.post(f"/api/rebuild/{job_id}")
    assert r.status_code == 200, r.text

    # Скачивание архива
    r = client.get(f"/api/download/{job_id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))

    assert "manifest.json" in names
    assert any(n.startswith(f"{target}/") for n in names), names
    assert not any(".." in n or n.startswith("/") for n in names)

    corrected = [p for p in manifest["pages"] if p["page_id"] == page0["page_id"]]
    assert corrected, manifest["pages"]
    assert corrected[0]["manual_correction"] is True
