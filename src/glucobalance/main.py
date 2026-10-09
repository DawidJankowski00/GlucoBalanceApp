"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from starlette.middleware.sessions import SessionMiddleware

from glucobalance.config import Settings, get_settings
from glucobalance.db import make_engine, make_session_factory
from glucobalance.web import auth, log, onboarding, pages, today
from glucobalance.web.deps import LoginRequired, login_required_handler
from glucobalance.web.rendering import STATIC_DIR, make_templates

SESSION_MAX_AGE_SECONDS = 14 * 24 * 3600


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the app. Tests can pass their own settings and database engine."""
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    # The login is a signed cookie holding only the user id. Lax SameSite stops other sites
    # from making the browser send it on a form POST; HTTPS-only outside development.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=SESSION_MAX_AGE_SECONDS,
        same_site="lax",
        https_only=settings.environment == "production",
    )
    app.state.session_factory = make_session_factory(engine or make_engine(settings.database_url))
    app.state.templates = make_templates(settings.app_name)
    app.add_exception_handler(LoginRequired, login_required_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(pages.router)
    app.include_router(log.router)
    app.include_router(today.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the app is running (used later by Docker and CI)."""
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    return app


app = create_app()
