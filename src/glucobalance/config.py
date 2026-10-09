"""Application settings, loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    # Reminders. The scheduler runs inside the web process; leave it on unless you run the
    # app in several processes (then enable it in exactly one). Unset means "on, except in
    # tests".
    scheduler_enabled: bool | None = None
    reminder_poll_seconds: int = Field(default=60, ge=5)
    # Web Push. Make a key pair with ``uv run python -m glucobalance.push``. Without a private
    # key reminders still appear in the app, but nothing is sent to phones.
    vapid_private_key: str | None = None
    vapid_public_key: str | None = None
    vapid_contact: str = "mailto:admin@example.com"
    # CGM import. The key encrypts the LibreLinkUp follower password in the database; make one
    # with ``uv run python -m glucobalance.cgm.crypto``. The job checks this often which CGM
    # connections are due (each has its own 1 to 5 minute interval).
    cgm_secret_key: str | None = None
    cgm_tick_seconds: int = Field(default=60, ge=15)

    @property
    def run_scheduler(self) -> bool:
        if self.scheduler_enabled is None:
            return self.environment != "test"
        return self.scheduler_enabled

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_private_key and self.vapid_public_key)

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key == DEV_SECRET_KEY:
            raise ValueError("GBA_SECRET_KEY must be set to a private value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the settings, built once and reused."""
    return Settings()
