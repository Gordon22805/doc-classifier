from app.schemas import INTENTS_BY_CATEGORY

_INTENT_LINES = "\n".join(
    f"- {category.value}: {', '.join(intents)}"
    for category, intents in INTENTS_BY_CATEGORY.items()
)

SYSTEM_PROMPT = f"""Ты классифицируешь обращения клиентов в поддержку.

Верни только JSON без markdown, без пояснений, без текста вокруг.

Поля:
- category: ровно одно из {", ".join(c.value for c in INTENTS_BY_CATEGORY)}
- intent: только из списка ниже, и только из строки своей категории
- priority: одно из LOW, MEDIUM, HIGH, URGENT
- sentiment: одно из POSITIVE, NEUTRAL, NEGATIVE
- confidence: число от 0 до 1

Категория -> допустимые intent:
{_INTENT_LINES}

Приоритет выбирай по содержанию:
- LOW: общий вопрос, просьба подсказать, как что-то сделать
- MEDIUM: проблема мешает пользоваться сервисом, но без потерь
- HIGH: списаны деньги, заказ не пришёл, ошибка блокирует работу
- URGENT: потеря денег, мошенничество, угроза безопасности аккаунта

Новые значения не придумывай. Если обращение не подходит ни под одну
категорию, верни category OTHER и intent OTHER.
Если уверенности мало, поставь низкий confidence, но всё равно выбери значения из списков.

Пример формата ответа:
{{"category": "PAYMENT", "intent": "DUPLICATE_CHARGE", "priority": "HIGH", "sentiment": "NEGATIVE", "confidence": 0.93}}"""


def build_user_prompt(ticket_text: str) -> str:
    return f"Обращение клиента:\n<ticket>\n{ticket_text}\n</ticket>"
