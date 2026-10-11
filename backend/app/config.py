from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Smart Operator API"
    database_url: str = "sqlite:///./smart_operator.db"
    evidence_dir: Path = Path("./data/evidence")
    reference_image_dir: Path = Path("./data/reference_images")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    verification_provider: str = "auto"
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
