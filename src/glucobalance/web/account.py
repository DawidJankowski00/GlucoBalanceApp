"""Account page: export your data as JSON or CSV, or delete the account."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from glucobalance import data_export
from glucobalance.accounts import verify_password
from glucobalance.demo_data import DEMO_EMAILS
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()


def _download(content: str | bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: CurrentUser, templates: Templates) -> HTMLResponse:
    return render(request, templates, "account.html", user, has_password=bool(user.password_hash))


@router.get("/account/export.json")
def export_json(user: CurrentUser, db: DbSession) -> Response:
    data = data_export.collect(db, user, now=datetime.now(UTC))
    return _download(data_export.to_json(data), "application/json", "glucobalance-export.json")


@router.get("/account/export.zip")
def export_csv(user: CurrentUser, db: DbSession) -> Response:
    data = data_export.collect(db, user, now=datetime.now(UTC))
    return _download(data_export.to_csv_zip(data), "application/zip", "glucobalance-export.zip")


@router.post("/account/delete", response_model=None)
def delete_account(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
    confirm_email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    """Delete after the user retypes their email (and password, where the account has one)."""
    problem = None
    if user.email in DEMO_EMAILS:
        problem = "The demo accounts are shared and cannot be deleted."
    elif confirm_email.strip().lower() != user.email:
        problem = "Type your email address exactly to confirm."
    elif user.password_hash and not verify_password(password, user.password_hash):
        problem = "The password is not right."
    if problem is not None:
        return render(
            request,
            templates,
            "account.html",
            user,
            status_code=422,
            error=problem,
            has_password=bool(user.password_hash),
        )
    data_export.delete_account(db, user)
    db.commit()
    request.session.clear()
    request.session["flash"] = "Your account and all its data were deleted."
    return RedirectResponse("/login", status_code=303)
