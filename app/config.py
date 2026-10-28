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

    omnirouter_api_key: Optional[str] = None
    # Адрес API OmniRouter и имя модели берутся из документации OmniRouter.
    # Пока они пустые, /predict отвечает 503 с понятной причиной.
    omnirouter_base_url: Optional[str] = None
    llm_model: Optional[str] = None

    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1
    llm_temperature: float = 0.0

    max_text_length: int = 4000
    max_tickets: int = 50

    @property
    def llm_configured(self) -> bool:
        return bool(self.omnirouter_api_key and self.omnirouter_base_url and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
