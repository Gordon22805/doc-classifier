"""Модели данных"""
from backend.models.schemas import (
    DocumentType,
    TextSource,
    ProcessingStatus,
    OCRProfile,
    ClassificationCandidate,
    PageDiagnostics,
    PageResult,
    JobStatus,
    TextQualityResult,
    OCRRequest,
    OCRResponse
)

__all__ = [
    "DocumentType",
    "TextSource",
    "ProcessingStatus",
    "OCRProfile",
    "ClassificationCandidate",
    "PageDiagnostics",
    "PageResult",
    "JobStatus",
    "TextQualityResult",
    "OCRRequest",
    "OCRResponse"
]
