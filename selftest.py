"""Полная проверка функционала сервиса.

Поднимает настоящий сервер uvicorn и гоняет реальные файлы через HTTP:
PDF с текстовым слоем, DOCX, многостраничные файлы, архивы, коррекцию,
пересборку, ZIP, защиту от Zip Slip и поведение без ключа.

Сканы требуют vision-модель. Чтобы проверить их без ключа и без сети,
поднимается локальная заглушка OpenAI-совместимого API.

Использование:
    py selftest.py            # без ключа: проверяется текстовый слой
    py selftest.py --mock     # с локальной заглушкой: проверяются и сканы
"""
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import fitz
import httpx
from docx import Document
from fastapi import FastAPI, Request
import uvicorn

PORT = 8077
MOCK_PORT = 8078
BASE = f"http://127.0.0.1:{PORT}"
PASS, FAIL = [], []

MOCK_TEXT = """РОССИЙСКАЯ ФЕДЕРАЦИЯ
ПАСПОРТ
Серия 45 00 Номер 123456
Выдан ОВД г. Москвы
Дата выдачи 15.03.2015"""


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "OK  " if cond else "ПРОВАЛ"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- генераторы файлов ----------

# Встроенный в PyMuPDF шрифт helv не содержит кириллицы, поэтому нужен
# системный шрифт. Путь ищется кроссплатформенно, чтобы тест работал в CI.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def find_cyrillic_font() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "Не найден шрифт с кириллицей. Установите fonts-dejavu-core (Linux) "
        "или проверьте C:\\Windows\\Fonts\\arial.ttf (Windows)."
    )


FONT_PATH = find_cyrillic_font()


def pdf_with_text(lines):
    """PDF с настоящим текстовым слоем (кириллица через системный шрифт)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname="arial", fontfile=FONT_PATH)
    for i, line in enumerate(lines):
        page.insert_text((50, 90 + i * 26), line, fontsize=13, fontname="arial")
    data = doc.tobytes()
    doc.close()
    return data


def pdf_scan_only():
    """PDF без текстового слоя: внутри только картинка."""
    src = fitz.open()
    page = src.new_page(width=595, height=842)
    page.insert_font(fontname="arial", fontfile=FONT_PATH)
    page.insert_text((60, 120), "PASSPORT SCAN", fontsize=28, fontname="arial")
    img = page.get_pixmap(dpi=150).tobytes("png")

    out = fitz.open()
    p = out.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=img)
    data = out.tobytes()
    src.close()
    out.close()
    return data


def docx_file(paragraphs):
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def zip_file(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------- заглушка провайдера ----------

def start_mock_provider() -> tuple:
    """Локальный OpenAI-совместимый сервер, отвечающий фиксированным текстом."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        body = await request.json()
        if not body.get("messages"):
            return {"error": "no messages"}
        return {
            "id": "mock-1",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "mock"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": MOCK_TEXT},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    config = uvicorn.Config(app, host="127.0.0.1", port=MOCK_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", MOCK_PORT), timeout=1):
                return server, thread
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("заглушка провайдера не запустилась")


# ---------- HTTP-помощники ----------

def run_job(client, name, data, content_type, timeout=120):
    r = client.post("/api/upload", files=[("files", (name, data, content_type))])
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = client.get(f"/api/status/{job_id}").json()
        if status["status"] not in ("pending", "processing"):
            return job_id, status
        time.sleep(0.3)
    return job_id, status


def wait_server(timeout=60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ---------- проверки ----------

def run_all(client, with_mock: bool) -> None:
    print("\n=== 1. Сервис отвечает ===")
    r = client.get("/api/health")
    check("GET /api/health = 200", r.status_code == 200, r.text[:100])
    h = r.json()
    check("health: status=healthy", h.get("status") == "healthy", str(h))
    check("health: модель указана", bool(h.get("vision_model")), str(h))
    check("health: base_url указан", bool(h.get("vision_base_url")), str(h))
    check("GET / — главная страница",
          client.get("/").status_code == 200 and len(client.get("/").text) > 1000)
    check("GET /docs — Swagger", client.get("/docs").status_code == 200)

    print("\n=== 2. PDF с текстовым слоем (без LLM) ===")
    data = pdf_with_text([
        "РОССИЙСКАЯ ФЕДЕРАЦИЯ",
        "ПАСПОРТ",
        "Серия 45 00 Номер 123456",
        "Выдан ОВД г. Москвы",
    ])
    job, st = run_job(client, "passport.pdf", data, "application/pdf")
    check("задача завершилась", st.get("status") == "success", str(st.get("status")))
    check("страниц = 1", st.get("total_pages") == 1, str(st.get("total_pages")))
    page = st["pages"][0]
    check("текст из слоя PDF", page["text_source"] == "text_layer", page["text_source"])
    check("тип = паспорт", page["doc_type"] == "passport", page["doc_type"])
    check("нет ошибки", not page.get("error"), str(page.get("error")))
    check("есть диагностика", bool(page.get("diagnostics")))

    print("\n=== 3. Классификация разных типов ===")
    cases = [
        ("выписка ЕГРН", ["ВЫПИСКА ИЗ ЕГРН", "Кадастровый номер 77:01:0001001:1234",
                          "Правообладатель: Иванов И.И."], "egrn"),
        ("платёжное поручение", ["ПЛАТЕЖНОЕ ПОРУЧЕНИЕ N 42", "Форма 0401060",
                                 "Получатель: ООО Ромашка"], "payment_order"),
        ("договор купли-продажи", ["ДОГОВОР КУПЛИ-ПРОДАЖИ КВАРТИРЫ", "г. Москва",
                                   "Продавец и Покупатель заключили настоящий договор"], "dkp"),
        ("паспорт РФ", ["ПАСПОРТ ГРАЖДАНИНА РОССИЙСКОЙ ФЕДЕРАЦИИ",
                        "Серия 45 00 Номер 123456"], "passport"),
    ]
    for label, lines, expected in cases:
        _, st = run_job(client, f"{label}.pdf", pdf_with_text(lines), "application/pdf")
        got = st["pages"][0]["doc_type"] if st.get("pages") else None
        check(f"{label} -> {expected}", got == expected, f"получено: {got}")

    # Неподдерживаемый тип должен честно уходить в unknown, а не угадываться
    _, st = run_job(client, "darenie.pdf",
                    pdf_with_text(["ДОГОВОР ДАРЕНИЯ", "г. Москва"]), "application/pdf")
    check("неизвестный тип -> unknown",
          st["pages"][0]["doc_type"] == "unknown", st["pages"][0]["doc_type"])

    print("\n=== 4. DOCX ===")
    d = docx_file(["ПАСПОРТ", "Серия 45 00 Номер 123456", "Выдан ОВД г. Москвы"])
    _, st = run_job(client, "doc.docx", d,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    check("DOCX обработан", st.get("status") == "success", str(st.get("status")))
    check("DOCX: тип = паспорт", st["pages"][0]["doc_type"] == "passport",
          st["pages"][0]["doc_type"])
    check("DOCX: источник = docx", st["pages"][0]["text_source"] == "docx",
          st["pages"][0]["text_source"])

    print("\n=== 5. Многостраничный PDF с разными типами ===")
    doc = fitz.open()
    for lines in (["ПАСПОРТ", "Серия 45 00 Номер 123456"],
                  ["ПЛАТЕЖНОЕ ПОРУЧЕНИЕ N 7", "Форма 0401060"],
                  ["ВЫПИСКА ИЗ ЕГРН", "Кадастровый номер 77:01:0001001:9999"]):
        page = doc.new_page(width=595, height=842)
        page.insert_font(fontname="arial", fontfile=FONT_PATH)
        for i, line in enumerate(lines):
            page.insert_text((50, 90 + i * 26), line, fontsize=13, fontname="arial")
    mixed = doc.tobytes()
    doc.close()
    _, st = run_job(client, "mixed.pdf", mixed, "application/pdf")
    types = [p["doc_type"] for p in st.get("pages", [])]
    check("3 страницы", len(types) == 3, str(types))
    check("типы различаются постранично", len(set(types)) == 3, str(types))
    check("нумерация страниц 1..3",
          [p["page_number"] for p in st["pages"]] == [1, 2, 3],
          str([p["page_number"] for p in st["pages"]]))

    print("\n=== 6. ZIP-архив с вложениями ===")
    inner = zip_file({
        "a_passport.pdf": pdf_with_text(["ПАСПОРТ", "Серия 45 00 Номер 123456"]),
        "b_payment.pdf": pdf_with_text(["ПЛАТЕЖНОЕ ПОРУЧЕНИЕ N 1", "Форма 0401060"]),
    })
    _, st = run_job(client, "bundle.zip", inner, "application/zip")
    check("архив обработан", st.get("status") == "success", str(st.get("status")))
    check("2 страницы из архива", st.get("total_pages") == 2, str(st.get("total_pages")))
    sources = {p["source_file"] for p in st.get("pages", [])}
    check("оба файла из архива", len(sources) == 2, str(sources))

    print("\n=== 7. Zip Slip: архив с выходом за папку ===")
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../evil.pdf", pdf_with_text(["ПАСПОРТ"]))
    _, st = run_job(client, "evil.zip", evil.getvalue(), "application/zip")
    check("архив с обходом путей отклонён",
          st.get("status") in ("error", "partial_error"), str(st.get("status")))
    check("файл не записан за пределы каталога",
          not os.path.exists(os.path.join("..", "..", "evil.pdf")))
    check("сервис жив после вредоносного архива",
          client.get("/api/health").status_code == 200)

    print("\n=== 8. Ручная коррекция и пересборка ===")
    job, st = run_job(client, "corr.pdf",
                      pdf_with_text(["ВЫПИСКА ИЗ ЕГРН",
                                     "Кадастровый номер 77:01:0001001:5555"]),
                      "application/pdf")
    pid = st["pages"][0]["page_id"]
    r = client.post(f"/api/correct/{job}/{pid}?doc_type=accounting")
    check("коррекция принята", r.status_code == 200, r.text[:150])
    check("новый тип в ответе", r.json().get("new_type") == "accounting", r.text[:150])

    r = client.post(f"/api/rebuild/{job}")
    check("пересборка = 200", r.status_code == 200, r.text[:150])

    st2 = client.get(f"/api/status/{job}").json()
    check("коррекция сохранилась",
          st2["pages"][0].get("corrected_type") == "accounting",
          str(st2["pages"][0].get("corrected_type")))
    check("флаг ручной правки", st2["pages"][0].get("manual_correction") is True)

    r = client.post(f"/api/correct/{job}/{pid}?doc_type=несуществующий")
    check("неверный тип отклонён", r.status_code in (400, 422), str(r.status_code))

    print("\n=== 9. Скачивание ZIP ===")
    r = client.get(f"/api/download/{job}")
    check("download = 200", r.status_code == 200, str(r.status_code))
    check("content-type = zip", r.headers.get("content-type") == "application/zip",
          r.headers.get("content-type"))
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
    check("есть manifest.json", "manifest.json" in names)
    check("папка по исправленному типу",
          any(n.startswith("accounting/") for n in names), str(names[:8]))
    check("есть изображения страниц",
          any(n.endswith((".jpg", ".jpeg")) for n in names), str(names[:8]))
    check("нет опасных путей",
          not any(".." in n or n.startswith(("/", "\\")) for n in names))
    check("manifest содержит страницу", len(manifest.get("pages", [])) >= 1)

    print("\n=== 10. Изображение страницы ===")
    r = client.get(f"/api/image/{job}/{pid}")
    check("image = 200", r.status_code == 200, r.text[:120])
    check("это JPEG", r.headers.get("content-type") == "image/jpeg",
          r.headers.get("content-type"))
    check("размер > 5 КБ", len(r.content) > 5000, f"{len(r.content)} байт")

    print("\n=== 11. Ошибки ввода ===")
    check("несуществующая задача = 404",
          client.get("/api/status/nonexistent").status_code == 404)
    check("скачивание несуществующей = 404",
          client.get("/api/download/nonexistent").status_code == 404)
    check("несуществующая картинка = 404",
          client.get(f"/api/image/{job}/nope").status_code == 404)

    r = client.post("/api/upload", files=[("files", ("x.pdf", b"not a pdf", "application/pdf"))])
    check("битый PDF принят без падения", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        bad_job = r.json()["job_id"]
        s = {}
        deadline = time.time() + 60
        while time.time() < deadline:
            s = client.get(f"/api/status/{bad_job}").json()
            if s["status"] not in ("pending", "processing"):
                break
            time.sleep(0.3)
        check("битый PDF дал ошибку, а не успех",
              s.get("status") in ("error", "partial_error"), s.get("status"))
    check("сервис жив после битого файла",
          client.get("/api/health").status_code == 200)

    print("\n=== 12. Скан без OCR ===")
    if with_mock:
        job, st = run_job(client, "scan.pdf", pdf_scan_only(), "application/pdf")
        check("скан обработан заглушкой", st.get("status") == "success",
              str(st.get("status")))
        p = st["pages"][0]
        check("источник = llm_ocr", p["text_source"] == "llm_ocr", p["text_source"])
        check("тип определён по OCR-тексту", p["doc_type"] == "passport", p["doc_type"])
        check("OCR-попытки зафиксированы",
              p["diagnostics"]["ocr_attempts"] >= 1,
              str(p["diagnostics"].get("ocr_attempts")))
        print(f"       попыток OCR: {p['diagnostics']['ocr_attempts']}, "
              f"профили: {p['diagnostics'].get('ocr_profiles_used')}")
    else:
        job, st = run_job(client, "scan.pdf", pdf_scan_only(), "application/pdf")
        check("скан без OCR даёт ошибку, а не зависание",
              st.get("status") in ("error", "partial_error"), str(st.get("status")))
        check("сервис жив после скана", client.get("/api/health").status_code == 200)
        if st.get("pages"):
            p = st["pages"][0]
            err = (p.get("diagnostics") or {}).get("error")
            print(f"       статус страницы: {p.get('status')}, ошибка: {err}")
            check("причина ошибки объяснена", bool(err), str(err))

        # Картинка без OCR — тоже честная ошибка, а не пустой «успех»
        img_doc = fitz.open()
        ip = img_doc.new_page(width=400, height=300)
        ip.insert_font(fontname="arial", fontfile=FONT_PATH)
        ip.insert_text((40, 80), "TEST IMAGE", fontsize=20, fontname="arial")
        img_bytes = ip.get_pixmap(dpi=120).tobytes("png")
        img_doc.close()
        _, st = run_job(client, "photo.png", img_bytes, "image/png")
        check("изображение без OCR -> ошибка",
              st.get("status") in ("error", "partial_error"), str(st.get("status")))
        check("сервис жив после изображения",
              client.get("/api/health").status_code == 200)


def main() -> int:
    with_mock = "--mock" in sys.argv

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["OCR_REQUEST_TIMEOUT"] = "20"
    env["OCR_MAX_RETRIES"] = "0"

    mock_server = None
    if with_mock:
        print("Запускаю заглушку провайдера...")
        mock_server, _ = start_mock_provider()
        env["OPENAI_API_KEY"] = "test-key"
        env["VISION_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
        env["VISION_MODEL"] = "mock-vision"
    else:
        env["OPENAI_API_KEY"] = ""
        print("Режим без ключа: OCR недоступен (как у пользователя без ключа).")

    print("Запускаю сервер...")
    log_path = "selftest_server.log"
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
        env=env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_server():
            print("ОШИБКА: сервер не запустился")
            log_file.close()
            with open(log_path, encoding="utf-8", errors="replace") as f:
                print(f.read()[-3000:])
            return 1
        with httpx.Client(base_url=BASE, timeout=120) as client:
            run_all(client, with_mock)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        if mock_server:
            mock_server.should_exit = True

    print("\n" + "=" * 55)
    print(f"ИТОГО: успешно {len(PASS)}, провалов {len(FAIL)}")
    if FAIL:
        print("\nПровалы:")
        for f in FAIL:
            print("  -", f)
    print("=" * 55)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
