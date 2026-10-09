"""Logging pages: quick manual entry of glucose readings, insulin doses and carbs."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.entries import EntryError, PossibleDuplicate
from glucobalance.favourites import add_favourite, delete_favourite, list_favourites, log_favourite
from glucobalance.foods import carbs_for_portion
from glucobalance.glucose_service import (
    is_low,
    log_reading,
    recent_readings,
    suggest_tag,
)
from glucobalance.models import DeliveryMode, DoseKind, GlucoseTag, InsulinType, User, UserSettings
from glucobalance.treatment_service import log_carbs, log_dose
from glucobalance.units import format_glucose
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.log_forms import (
    local_input_value,
    parse_carb_form,
    parse_dose_form,
    parse_glucose_form,
)
from glucobalance.web.rendering import render

router = APIRouter(prefix="/log")

HYPO_KEY = "show_hypo_steps"
TAG_LABELS = {
    GlucoseTag.FASTING: "Fasting",
    GlucoseTag.BEFORE_MEAL: "Before meal",
    GlucoseTag.AFTER_MEAL: "After meal",
    GlucoseTag.BEDTIME: "Bedtime",
    GlucoseTag.NIGHT: "Night",
}

DOSE_KIND_LABELS = {
    DoseKind.BOLUS: "Meal bolus",
    DoseKind.CORRECTION: "Correction",
    DoseKind.BASAL: "Basal",
}
INSULIN_LABELS = {InsulinType.RAPID: "Rapid-acting", InsulinType.LONG: "Long-acting"}


def _now() -> datetime:
    return datetime.now(UTC)


def _zone(settings: UserSettings) -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _glucose_page(
    request: Request,
    templates: Templates,
    db: DbSession,
    user: User,
    settings: UserSettings,
    values: dict[str, str],
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    zone = _zone(settings)
    recent: list[dict[str, Any]] = [
        {
            "when": r.measured_at.astimezone(zone),
            "value": format_glucose(r.value_mgdl, settings.display_unit),
            "low": r.value_mgdl < settings.target_low_mgdl,
            "high": r.value_mgdl > settings.target_high_mgdl,
            "tag": TAG_LABELS.get(r.tag) if r.tag else None,
            "note": r.note,
        }
        for r in recent_readings(db, user)
    ]
    return render(
        request,
        templates,
        "log/glucose.html",
        user,
        status_code=status_code,
        values=values,
        tags=TAG_LABELS,
        unit=settings.display_unit.value,
        recent=recent,
        show_hypo=request.session.pop(HYPO_KEY, False),
        clinician=settings.clinician_contact,
        error=error,
    )


@router.get("/glucose", response_model=None)
def glucose_form(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    now = _now()
    zone = _zone(settings)
    tag = suggest_tag(now.astimezone(zone).time())
    values = {
        "value": "",
        "measured_at": local_input_value(now, zone),
        "tag": tag.value if tag else "",
        "note": "",
    }
    return _glucose_page(request, templates, db, user, settings, values)


@router.post("/glucose", response_model=None)
async def save_glucose(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = {k: str(v) for k, v in (await request.form()).items()}
    zone = _zone(settings)
    try:
        entry = parse_glucose_form(form, settings.display_unit, zone)
        reading = log_reading(db, user, entry, now=_now())
    except EntryError as error:
        db.rollback()
        return _glucose_page(
            request, templates, db, user, settings, form, error=str(error), status_code=422
        )
    db.commit()
    shown = format_glucose(reading.value_mgdl, settings.display_unit)
    request.session["flash"] = f"Saved {shown} at {reading.measured_at.astimezone(zone):%H:%M}."
    if is_low(reading.value_mgdl):
        request.session[HYPO_KEY] = True
    return RedirectResponse("/log/glucose", status_code=303)


def _insulin_page(
    request: Request,
    templates: Templates,
    user: User,
    settings: UserSettings,
    values: dict[str, str],
    *,
    error: str | None = None,
    ask_confirm: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    pens = settings.delivery_mode is DeliveryMode.PENS
    return render(
        request,
        templates,
        "log/insulin.html",
        user,
        status_code=status_code,
        values=values,
        kinds=DOSE_KIND_LABELS,
        insulins=INSULIN_LABELS if pens else {InsulinType.RAPID: "Rapid-acting"},
        step=format(settings.dose_step_units.normalize(), "f"),
        max_bolus=format(settings.max_bolus_units.normalize(), "f"),
        ask_confirm=ask_confirm,
        error=error,
    )


@router.get("/insulin", response_model=None)
def insulin_form(
    request: Request, user: CurrentUser, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    values = {
        "units": "",
        "insulin_type": InsulinType.RAPID.value,
        "kind": DoseKind.BOLUS.value,
        "taken_at": local_input_value(_now(), _zone(settings)),
    }
    return _insulin_page(request, templates, user, settings, values)


@router.post("/insulin", response_model=None)
async def save_insulin(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = {k: str(v) for k, v in (await request.form()).items()}
    zone = _zone(settings)
    try:
        dose = log_dose(db, user, parse_dose_form(form, zone), now=_now())
    except EntryError as error:
        db.rollback()
        return _insulin_page(
            request,
            templates,
            user,
            settings,
            form,
            error=str(error),
            ask_confirm=isinstance(error, PossibleDuplicate),
            status_code=422,
        )
    db.commit()
    request.session["flash"] = (
        f"Saved {format(dose.units.normalize(), 'f')} units"
        f" ({DOSE_KIND_LABELS[dose.kind].lower()}) at {dose.taken_at.astimezone(zone):%H:%M}."
    )
    return RedirectResponse("/log/insulin", status_code=303)


def _carbs_page(
    request: Request,
    templates: Templates,
    db: DbSession,
    user: User,
    values: dict[str, str],
    *,
    error: str | None = None,
    ask_confirm: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    favourites = [
        {
            "id": meal.id,
            "name": meal.name,
            "grams": format(meal.grams.normalize(), "f"),
            "description": meal.description,
        }
        for meal in list_favourites(db, user)
    ]
    return render(
        request,
        templates,
        "log/carbs.html",
        user,
        status_code=status_code,
        values=values,
        favourites=favourites,
        ask_confirm=ask_confirm,
        error=error,
    )


def _prefill_from_food(description: str, per100: str, portion: str) -> dict[str, str]:
    """Form values for a food picked in the search: its name and the carbs of the portion."""
    values = {"description": description.strip()[:200]}
    try:
        grams = carbs_for_portion(Decimal(per100), Decimal(portion))
    except (InvalidOperation, EntryError):
        return values
    values["grams"] = format(grams, "f")
    return values


@router.get("/carbs", response_model=None)
def carbs_form(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
    description: str = "",
    per100: str = "",
    portion: str = "",
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    values = {
        "grams": "",
        "eaten_at": local_input_value(_now(), _zone(settings)),
        "description": "",
        "favourite_name": "",
    }
    if description or per100:
        values.update(_prefill_from_food(description, per100, portion))
    return _carbs_page(request, templates, db, user, values)


@router.post("/carbs", response_model=None)
async def save_carbs(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = {k: str(v) for k, v in (await request.form()).items()}
    zone = _zone(settings)
    try:
        entry = log_carbs(db, user, parse_carb_form(form, zone), now=_now())
    except EntryError as error:
        db.rollback()
        return _carbs_page(
            request,
            templates,
            db,
            user,
            form,
            error=str(error),
            ask_confirm=isinstance(error, PossibleDuplicate),
            status_code=422,
        )
    grams = format(entry.grams.normalize(), "f")
    message = f"Saved {grams} g at {entry.eaten_at.astimezone(zone):%H:%M}."
    favourite_name = form.get("favourite_name", "").strip()
    if favourite_name:
        try:
            add_favourite(db, user, favourite_name, entry.grams, entry.description)
            message += f" Saved as favourite meal {favourite_name}."
        except EntryError as problem:
            message += f" Not saved as a favourite: {problem}"
    db.commit()
    request.session["flash"] = message
    return RedirectResponse("/log/carbs", status_code=303)


@router.post("/favourites/{favourite_id}/log", response_model=None)
def log_favourite_now(
    favourite_id: int, request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    zone = _zone(settings)
    try:
        entry = log_favourite(db, user, favourite_id, now=_now())
    except EntryError as error:
        db.rollback()
        message = str(error)
        if isinstance(error, PossibleDuplicate):
            message += " Use the form below and tick the box if you ate it twice."
        values = {
            "grams": "",
            "eaten_at": local_input_value(_now(), zone),
            "description": "",
            "favourite_name": "",
        }
        return _carbs_page(request, templates, db, user, values, error=message, status_code=422)
    db.commit()
    grams = format(entry.grams.normalize(), "f")
    request.session["flash"] = f"Saved {grams} g at {entry.eaten_at.astimezone(zone):%H:%M}."
    return RedirectResponse("/log/carbs", status_code=303)


@router.post("/favourites/{favourite_id}/delete", response_model=None)
def delete_favourite_now(
    favourite_id: int, request: Request, user: CurrentUser, db: DbSession
) -> RedirectResponse:
    if delete_favourite(db, user, favourite_id):
        db.commit()
        request.session["flash"] = "Favourite meal deleted."
    return RedirectResponse("/log/carbs", status_code=303)
