"""FastAPI dependencies shared by the routes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from glucobalance.models import User

SESSION_USER_KEY = "user_id"


class LoginRequired(Exception):
    """Raised by ``current_user`` when nobody is logged in; the app turns it into a redirect."""


def login_required_handler(_request: Request, _exc: Exception) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def get_db(request: Request) -> Iterator[Session]:
    """One database session per request, closed afterwards. Routes commit explicitly."""
    with request.app.state.session_factory() as session:
        yield session


def get_templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        request.session.clear()
        raise LoginRequired
    return user


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
Templates = Annotated[Jinja2Templates, Depends(get_templates)]
