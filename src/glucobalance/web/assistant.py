"""The assistant chat and the weekly review page."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.adjustment_service import REVIEW_PERIOD_DAYS, SuggestionError
from glucobalance.agent import forget, history, respond
from glucobalance.analytics_service import build_analytics
from glucobalance.llm import LLMClient, LLMError
from glucobalance.models import DisplayUnit, StoredSuggestion, UserSettings
from glucobalance.units import mgdl_to_mmoll
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render
from glucobalance.weekly_review import accept, pending, recent_decisions, reject, run_review

router = APIRouter()

SETTING_LABELS = {"icr": "Carb ratio (ICR)", "isf": "Sensitivity (ISF)"}


def _now() -> datetime:
    return datetime.now(UTC)


def _llm(request: Request) -> LLMClient | None:
    client: LLMClient | None = request.app.state.llm
    return client


def describe_value(setting: str, value: Decimal, unit: DisplayUnit) -> str:
    """A suggested value with its unit, ISF in the user's glucose unit."""
    if setting == "icr":
        return f"{value.normalize():f} g per unit"
    if unit is DisplayUnit.MMOLL:
        return f"{mgdl_to_mmoll(float(value)):.1f} mmol/L per unit"
    return f"{int(value)} mg/dL per unit"


@router.get("/assistant", response_model=None)
def assistant_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    client = _llm(request)
    return render(
        request,
        templates,
        "assistant.html",
        user,
        messages=history(db, user),
        enabled=client is not None,
        model=client.name if client is not None else None,
    )


@router.post("/assistant", response_model=None)
def ask(
    request: Request, user: CurrentUser, db: DbSession, question: str = Form("")
) -> RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    client = _llm(request)
    if client is None:
        request.session["flash"] = "The assistant is not set up on this server."
    elif not question.strip():
        request.session["flash"] = "Type a question first."
    else:
        try:
            respond(db, user, client, question, now=_now())
            db.commit()
        except LLMError as error:
            db.rollback()
            request.session["flash"] = str(error)
    return RedirectResponse("/assistant#latest", status_code=303)


@router.post("/assistant/clear")
def clear(request: Request, user: CurrentUser, db: DbSession) -> RedirectResponse:
    forget(db, user)
    db.commit()
    request.session["flash"] = "Conversation cleared."
    return RedirectResponse("/assistant", status_code=303)


@router.get("/assistant/review", response_model=None)
def review_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings: UserSettings | None = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    data = build_analytics(db, user, days=REVIEW_PERIOD_DAYS, now=_now())
    unit = data.unit

    def shown(mgdl: float) -> str:
        if unit is DisplayUnit.MMOLL:
            return f"{mgdl_to_mmoll(mgdl):.1f} {unit.value}"
        return f"{mgdl:.0f} {unit.value}"

    def value(row: StoredSuggestion, amount: Decimal) -> str:
        return describe_value(row.setting, amount, unit)

    return render(
        request,
        templates,
        "assistant_review.html",
        user,
        data=data,
        shown=shown,
        suggestions=pending(db, user),
        decisions=recent_decisions(db, user),
        labels=SETTING_LABELS,
        value=value,
    )


@router.post("/assistant/review", response_model=None)
def run(request: Request, user: CurrentUser, db: DbSession) -> RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    review = run_review(db, user, now=_now())
    db.commit()
    count = len(review.suggestions)
    request.session["flash"] = (
        f"Review done: {count} suggestion{'s' if count != 1 else ''} to decide on."
        if count
        else "Review done: no setting changes are suggested."
    )
    return RedirectResponse("/assistant/review", status_code=303)


@router.post("/assistant/suggestions/{suggestion_id}/{decision}")
def decide(
    request: Request, user: CurrentUser, db: DbSession, suggestion_id: int, decision: str
) -> RedirectResponse:
    try:
        if decision == "accept":
            accept(db, user, suggestion_id, now=_now())
            request.session["flash"] = "Change saved. You can see it in your settings history."
        elif decision == "reject":
            reject(db, user, suggestion_id, now=_now())
            request.session["flash"] = "Suggestion rejected. Nothing changed."
        else:
            request.session["flash"] = "Unknown choice."
        db.commit()
    except SuggestionError as error:
        db.rollback()
        request.session["flash"] = str(error)
    return RedirectResponse("/assistant/review", status_code=303)
