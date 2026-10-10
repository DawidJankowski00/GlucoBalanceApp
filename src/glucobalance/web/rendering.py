"""Template rendering helpers."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import object_session

from glucobalance.demo_data import DEMO_EMAILS
from glucobalance.features import feature_flags
from glucobalance.models import User
from glucobalance.reminder_service import unread_count

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def make_templates(app_name: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=TEMPLATE_DIR)
    templates.env.globals["app_name"] = app_name
    return templates


def render(
    request: Request,
    templates: Jinja2Templates,
    name: str,
    user: User | None = None,
    *,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    """Render a template with the logged-in user, their feature flags and any flash message."""
    flags = None
    unread = 0
    if user is not None and user.settings is not None:
        flags = feature_flags(user.settings.delivery_mode, user.settings.monitoring_mode)
        # The user was loaded by this request's session; reuse it for the badge count.
        session = object_session(user)
        if session is not None:
            unread = unread_count(session, user)
    context.update(
        user=user,
        flags=flags,
        unread=unread,
        flash=request.session.pop("flash", None),
        demo_mode=request.app.state.settings.demo_mode,
        is_demo=user is not None and user.email in DEMO_EMAILS,
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)
