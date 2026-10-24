import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения из переменных окружения"""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'  # не падаем на устаревших переменных (например, PADDLE_OCR_*)
    )
    
    # OCR (vision-модель через OpenAI-совместимый API)
    # По умолчанию — OpenRouter. Ключ: https://openrouter.ai/keys
    openai_api_key: Optional[str] = None
    vision_model: str = "qwen/qwen2.5-vl-72b-instruct:free"
    vision_base_url: Optional[str] = "https://openrouter.ai/api/v1"
    
    # PDF Processing
    pdf_render_dpi: int = 220
    max_image_side: int = 3200
    jpeg_quality: int = 95
    
    # OCR Retry
    ocr_tiled_retry_enabled: bool = True
    ocr_tile_overlap: float = 0.18
    ocr_batch_size: int = 2
    ocr_global_concurrency: int = 4
    
    # OCR Timeouts
    ocr_connect_timeout: int = 5
    ocr_request_timeout: int = 120
    ocr_max_retries: int = 2
    
    # Classification
    min_classification_score: float = 2.0
    min_score_margin: float = 2.0
    
    # Archive Safety
    max_archive_files: int = 1000
    max_file_size_mb: int = 100
    max_total_unpack_size_mb: int = 500
    max_nested_archives: int = 2
    
    # Text Quality
    min_text_length: int = 10
    max_replacement_char_ratio: float = 0.15
    min_alnum_ratio: float = 0.3
    max_repeat_length: int = 10
    max_cid_ratio: float = 0.1
    
    # Application
    host: str = "0.0.0.0"
    port: int = 8000
    temp_dir: str = "./temp"
    upload_dir: str = "./uploads"
    results_dir: str = "./results"


settings = Settings()
