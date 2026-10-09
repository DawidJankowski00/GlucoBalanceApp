"""Application settings, loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-secret-change-me"


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
    # Signs the login cookie. Set a long random value in production (GBA_SECRET_KEY).
    secret_key: str = DEV_SECRET_KEY

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key == DEV_SECRET_KEY:
            raise ValueError("GBA_SECRET_KEY must be set to a private value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the settings, built once and reused."""
    return Settings()
