from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Manufacturing Platform API"
    database_url: str = "sqlite:///./manufacturing_platform.db"
    evidence_dir: Path = Path("./data/evidence")
    reference_image_dir: Path = Path("./data/reference_images")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    cors_origins: str = "http://localhost:8082,http://127.0.0.1:8082"
    session_secure: bool = False
    session_hours: int = 12
    machine_event_token: str | None = None
    admin_integration_token: str | None = None
    gateway_timeout: float = 3.0
    machine_callback_url: str = "http://127.0.0.1:8083/api/machine/events"


@lru_cache
def get_settings() -> Settings:
    return Settings()
