"""Application settings, loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Each field maps to an env var with the GBA_ prefix (GBA_DEBUG, ...)."""

    model_config = SettingsConfigDict(
        env_prefix="GBA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "GlucoBalanceApp"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    database_url: str = "postgresql+psycopg://glucobalance:change-me@localhost:5432/glucobalance"


@lru_cache
def get_settings() -> Settings:
    """Return the settings, built once and reused."""
    return Settings()
