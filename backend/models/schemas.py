from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Типы поддерживаемых документов"""
    PASSPORT = "passport"
    EGRN = "egrn"
    DKP = "dkp"  # Договор купли-продажи
    PDKP = "pdkp"  # Предварительный договор купли-продажи
    DDU = "ddu"  # Договор долевого участия
    ZAGS = "zags"  # Документы ЗАГС
    INHERITANCE = "inheritance"  # Документы о наследстве
    EZD = "ezd"  # ЕЖД
    NDFL = "ndfl"  # НДФЛ
    SFR = "sfr"  # Документы СФР
    PAYMENT_ORDER = "payment_order"  # Платёжное поручение
    ACCOUNTING = "accounting"  # Бухгалтерская отчётность
    REFERENCE = "reference"  # Справки
    UNKNOWN = "unknown"


class TextSource(str, Enum):
    """Источник текста страницы"""
    TEXT_LAYER = "text_layer"
    LLM_OCR = "llm_ocr"
    FOCUSED = "focused"
    ENHANCED = "enhanced"
    TILED = "tiled"
    DOCX = "docx"


class ProcessingStatus(str, Enum):
    """Статус обработки"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    PARTIAL_ERROR = "partial_error"
    ERROR = "error"


class OCRProfile(str, Enum):
    """Профили чувствительности OCR"""
    ORIGINAL = "original"
    FOCUSED = "focused"
    ENHANCED = "enhanced"
    TILE = "tile"


class ClassificationCandidate(BaseModel):
    """Кандидат классификации"""
    doc_type: DocumentType
    score: float
    rule_name: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class PageDiagnostics(BaseModel):
    """Диагностическая информация о странице"""
    source_file: str
    page_number: int
    text_source: TextSource
    text_length: int
    ocr_attempts: int = 0
    ocr_profiles_used: List[str] = Field(default_factory=list)
    quality_check_passed: bool = False
    quality_issues: List[str] = Field(default_factory=list)
    classification_score: Optional[float] = None
    score_margin: Optional[float] = None
    rule_applied: Optional[str] = None
    top_candidates: List[ClassificationCandidate] = Field(default_factory=list)
    processing_time_ms: float = 0
    error: Optional[str] = None


class PageResult(BaseModel):
    """Результат обработки страницы"""
    page_id: str
    source_file: str
    page_number: int
    doc_type: DocumentType
    confidence: float
    text_source: TextSource
    status: ProcessingStatus
    image_path: Optional[str] = None
    diagnostics: PageDiagnostics
    manual_correction: bool = False
    corrected_type: Optional[DocumentType] = None


class JobStatus(BaseModel):
    """Статус задачи обработки"""
    job_id: str
    status: ProcessingStatus
    total_files: int = 0
    total_pages: int = 0
    processed_pages: int = 0
    pages: List[PageResult] = Field(default_factory=list)
    result_zip_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class TextQualityResult(BaseModel):
    """Результат проверки качества текста"""
    is_good: bool
    score: float
    issues: List[str] = Field(default_factory=list)
    metrics: Dict[str, float] = Field(default_factory=dict)


class OCRRequest(BaseModel):
    """Запрос к OCR сервису"""
    file: str  # Base64
    fileType: int = 1
    useDocOrientationClassify: bool = True
    useDocUnwarping: bool = False
    useTextlineOrientation: bool = True
    textDetLimitSideLen: int = 3200
    textDetLimitType: str = "max"
    visualize: bool = False
    # Профильные параметры
    textDetThresh: Optional[float] = None
    textDetBoxThresh: Optional[float] = None
    textDetUnclipRatio: Optional[float] = None
    textRecScoreThresh: Optional[float] = None


class OCRResponse(BaseModel):
    """Ответ от OCR сервиса"""
    text: str = ""
    confidence: Optional[float] = None
    method: Optional[str] = None  # Метод распознавания (gpt4_vision_original, и т.д.)
    raw_response: Dict[str, Any] = Field(default_factory=dict)
