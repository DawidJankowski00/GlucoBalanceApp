"""Template rendering helpers."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from glucobalance.features import feature_flags
from glucobalance.models import User

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
    if user is not None and user.settings is not None:
        flags = feature_flags(user.settings.delivery_mode, user.settings.monitoring_mode)
    context.update(user=user, flags=flags, flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)
