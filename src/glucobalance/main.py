"""FastAPI application entry point."""

from fastapi import FastAPI

from glucobalance.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests can pass their own settings."""
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the app is running (used later by Docker and CI)."""
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    return app


app = create_app()
