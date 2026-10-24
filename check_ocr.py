"""Быстрая проверка OCR-провайдера одним запросом.

Использование:
    py check_ocr.py                  # проверка по настройкам из .env
    py check_ocr.py --model gemini-2.5-flash
"""
import argparse
import asyncio
import sys

from backend.config import settings
from backend.core.ocr_client import OCRClient


def make_test_image() -> bytes:
    """Картинка с русским текстом — имитация скана документа."""
    import fitz
    from pathlib import Path

    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    font_path = next((Path(p) for p in candidates if Path(p).exists()), None)

    doc = fitz.open()
    page = doc.new_page(width=600, height=300)
    if font_path:
        page.insert_font(fontname="arial", fontfile=str(font_path))
        font = "arial"
    else:
        font = "helv"
    page.insert_text((40, 80), "РОССИЙСКАЯ ФЕДЕРАЦИЯ", fontsize=20, fontname=font)
    page.insert_text((40, 130), "ПАСПОРТ", fontsize=24, fontname=font)
    page.insert_text((40, 180), "Серия 45 00 Номер 123456", fontsize=18, fontname=font)
    page.insert_text((40, 230), "Выдан ОВД г. Москвы", fontsize=16, fontname=font)
    jpeg = page.get_pixmap(dpi=150).tobytes("jpeg")
    doc.close()
    return jpeg


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    client = OCRClient()
    if args.model:
        client.model = args.model
    if args.base_url:
        client.base_url = args.base_url
        client.client = None  # пересоздадим ниже
        import openai
        client.client = openai.AsyncOpenAI(
            api_key=client.api_key or "local",
            base_url=args.base_url,
            timeout=client.request_timeout,
        )

    print(f"провайдер : {client.base_url or 'api.openai.com'}")
    print(f"модель    : {client.model}")
    print(f"ключ      : {'задан' if client.api_key else 'НЕ задан'}")
    print()

    if not client.is_available():
        print("ОШИБКА: OCR не настроен. Задайте OPENAI_API_KEY в .env")
        return 1

    image = make_test_image()
    print(f"изображение: {len(image)} байт, отправляю...\n")

    try:
        result = await client.recognize(image)
    except Exception as exc:
        print(f"ОШИБКА OCR: {exc}")
        return 1

    print(f"уверенность : {result.confidence}")
    print(f"метод       : {result.method}")
    print(f"длина текста: {len(result.text)} символов")
    print("\n--- распознанный текст ---")
    print(result.text or "(пусто)")
    print("--- конец ---")

    if not result.text.strip():
        print("\nМодель вернула пустой текст — проверьте название модели.")
        return 1

    checks = {
        "ПАСПОРТ": "ПАСПОРТ" in result.text.upper(),
        "45 00": "45" in result.text and "123456" in result.text.replace(" ", ""),
    }
    print("\nпроверки:")
    for name, ok in checks.items():
        print(f"  {'OK  ' if ok else 'НЕТ '} {name}")

    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
