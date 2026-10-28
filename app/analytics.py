import asyncio
import csv
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List

from app.classifier import TicketClassifier
from app.schemas import PredictionResponse

logger = logging.getLogger(__name__)


def load_sample_tickets(path: Path, limit: int) -> List[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row["text"].strip() for row in rows[:limit] if row.get("text", "").strip()]


def summarize(results: List[PredictionResponse]) -> Dict[str, Dict[str, float]]:
    def distribution(values: List[str]) -> Dict[str, float]:
        counts = Counter(values)
        total = len(values) or 1
        return {
            key: round(count / total * 100, 1)
            for key, count in counts.most_common()
        }

    return {
        "category": distribution([r.category.value for r in results]),
        "priority": distribution([r.priority.value for r in results]),
        "department": distribution([r.department for r in results]),
        "sentiment": distribution([r.sentiment.value for r in results]),
    }


async def analyze(
    texts: List[str],
    classifier: TicketClassifier,
    concurrency: int = 4,
) -> Dict[str, object]:
    """Каждый тикет уходит в LLM ровно один раз."""
    semaphore = asyncio.Semaphore(concurrency)
    failures: List[Dict[str, str]] = []

    async def run(text: str) -> PredictionResponse | None:
        async with semaphore:
            try:
                return await classifier.classify(text)
            except Exception as exc:
                logger.warning("Тикет пропущен: %s", type(exc).__name__)
                failures.append({"text": text[:80], "error": str(exc)})
                return None

    results = [r for r in await asyncio.gather(*(run(t) for t in texts)) if r]
    return {
        "processed": len(results),
        "failed": len(failures),
        "failures": failures,
        "distribution": summarize(results),
        "results": [r.model_dump() for r in results],
    }
