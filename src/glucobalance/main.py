"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from starlette.middleware.sessions import SessionMiddleware

from glucobalance.config import Settings, get_settings
from glucobalance.db import make_engine, make_session_factory
from glucobalance.foods import CachedFoodSource, FoodSource, OpenFoodFacts
from glucobalance.push import PushSender, WebPushSender
from glucobalance.scheduler import build_scheduler
from glucobalance.web import (
    auth,
    chart_page,
    food,
    hypo,
    log,
    logbook_pages,
    onboarding,
    pages,
    push,
    reminders,
    sites,
    today,
)
from glucobalance.web.deps import LoginRequired, login_required_handler
from glucobalance.web.rendering import STATIC_DIR, make_templates

SESSION_MAX_AGE_SECONDS = 14 * 24 * 3600


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    food_source: FoodSource | None = None,
    push_sender: PushSender | None = None,
) -> FastAPI:
    """Build the app. Tests can pass their own settings, database engine and food source."""
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    if push_sender is None and settings.push_enabled:
        assert settings.vapid_private_key is not None
        push_sender = WebPushSender(settings.vapid_private_key, settings.vapid_contact)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Start the reminder scheduler with the app and stop it again on shutdown."""
        if settings.run_scheduler:
            scheduler = build_scheduler(settings, engine, session_factory, push_sender)
            scheduler.start()
            app.state.scheduler = scheduler
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.scheduler = None
    app.state.push_sender = push_sender
    app.state.settings = settings

    # The login is a signed cookie holding only the user id. Lax SameSite stops other sites
    # from making the browser send it on a form POST; HTTPS-only outside development.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=SESSION_MAX_AGE_SECONDS,
        same_site="lax",
        https_only=settings.environment == "production",
    )
    app.state.session_factory = session_factory
    app.state.templates = make_templates(settings.app_name)
    app.state.food_source = food_source or CachedFoodSource(OpenFoodFacts())
    app.add_exception_handler(LoginRequired, login_required_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(pages.router)
    app.include_router(log.router)
    app.include_router(food.router)
    app.include_router(hypo.router)
    app.include_router(today.router)
    app.include_router(chart_page.router)
    app.include_router(logbook_pages.router)
    app.include_router(sites.router)
    app.include_router(reminders.router)
    app.include_router(push.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the app is running (used later by Docker and CI)."""
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    return app


app = create_app()
