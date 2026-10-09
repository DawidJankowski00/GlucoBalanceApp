import pytest
from pydantic import ValidationError

from glucobalance.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_NAME", "ENVIRONMENT", "DEBUG", "DATABASE_URL", "SECRET_KEY"):
        monkeypatch.delenv(f"GBA_{name}", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_name == "GlucoBalanceApp"
    assert settings.environment == "development"
    assert settings.debug is False


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GBA_ENVIRONMENT", "production")
    monkeypatch.setenv("GBA_DEBUG", "true")
    monkeypatch.setenv("GBA_DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("GBA_SECRET_KEY", "x" * 40)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.environment == "production"
    assert settings.debug is True
    assert settings.database_url == "sqlite:///test.db"


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GBA_ENVIRONMENT", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_production_requires_a_private_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GBA_SECRET_KEY", raising=False)
    monkeypatch.setenv("GBA_ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="GBA_SECRET_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setenv("GBA_SECRET_KEY", "x" * 40)
    assert Settings(_env_file=None).environment == "production"  # type: ignore[call-arg]
