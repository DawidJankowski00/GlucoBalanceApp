"""Sign-up, login and logout."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.accounts import AccountError, authenticate, register
from glucobalance.web.deps import SESSION_USER_KEY, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()


def _log_in(request: Request, user_id: int) -> RedirectResponse:
    request.session.clear()  # a fresh session after login
    request.session[SESSION_USER_KEY] = user_id
    return RedirectResponse("/", status_code=303)


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, templates: Templates) -> HTMLResponse:
    return render(request, templates, "auth/signup.html")


@router.post("/signup", response_model=None)
def signup(
    request: Request,
    db: DbSession,
    templates: Templates,
    email: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    try:
        user = register(db, email, display_name, password)
    except AccountError as error:
        return render(
            request,
            templates,
            "auth/signup.html",
            status_code=422,
            error=str(error),
            email=email,
            display_name=display_name,
        )
    db.commit()
    return _log_in(request, user.id)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, templates: Templates) -> HTMLResponse:
    return render(request, templates, "auth/login.html")


@router.post("/login", response_model=None)
def login(
    request: Request,
    db: DbSession,
    templates: Templates,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    user = authenticate(db, email, password)
    if user is None:
        return render(
            request,
            templates,
            "auth/login.html",
            status_code=401,
            error="Wrong email or password.",
            email=email,
        )
    return _log_in(request, user.id)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
