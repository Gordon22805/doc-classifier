from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Заглушки: адрес и модель OpenRouter уже подставлены, ключ нужно вписать
    # самому в .env. Пока ключа нет, /predict отвечает 503 с понятной причиной.
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = "https://openrouter.ai/api/v1"
    llm_model: Optional[str] = "google/gemma-4-31b-it:free"

    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1
    llm_temperature: float = 0.0

    max_text_length: int = 4000
    max_tickets: int = 50

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_base_url and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
