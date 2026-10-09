"""The hypo log page: record what was taken to treat a low."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.entries import EntryError, PossibleDuplicate
from glucobalance.hypo_service import RECHECK_MINUTES, log_hypo, recent_hypos
from glucobalance.models import HypoTreatmentKind, User, UserSettings
from glucobalance.units import format_glucose
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.log_forms import local_input_value, parse_hypo_form
from glucobalance.web.rendering import render

router = APIRouter(prefix="/log")

TREATMENT_LABELS = {
    HypoTreatmentKind.GLUCOSE_TABLETS: "Glucose tablets",
    HypoTreatmentKind.JUICE: "Juice",
    HypoTreatmentKind.SWEETS: "Sweets",
    HypoTreatmentKind.FOOD: "Food",
    HypoTreatmentKind.GLUCAGON: "Glucagon",
    HypoTreatmentKind.OTHER: "Other",
}
GLUCAGON_MESSAGE = (
    "Logged glucagon. If the person is not waking up or cannot swallow, call the emergency"
    " number, and tell your diabetes team afterwards."
)


def _now() -> datetime:
    return datetime.now(UTC)


def _page(
    request: Request,
    templates: Templates,
    db: DbSession,
    user: User,
    settings: UserSettings,
    values: dict[str, str],
    *,
    error: str | None = None,
    ask_confirm: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    zone = ZoneInfo(settings.timezone)
    recent = [
        {
            "when": t.treated_at.astimezone(zone),
            "treatment": TREATMENT_LABELS[t.treatment],
            "carbs": format(t.carbs_grams.normalize(), "f") if t.carbs_grams else None,
            "reading": format_glucose(t.reading.value_mgdl, settings.display_unit)
            if t.reading
            else None,
            "note": t.note,
        }
        for t in recent_hypos(db, user)
    ]
    return render(
        request,
        templates,
        "log/hypo.html",
        user,
        status_code=status_code,
        values=values,
        treatments=TREATMENT_LABELS,
        recent=recent,
        ask_confirm=ask_confirm,
        clinician=settings.clinician_contact,
        error=error,
    )


@router.get("/hypo", response_model=None)
def hypo_form(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    values = {
        "treatment": "",
        "carbs_grams": "",
        "treated_at": local_input_value(_now(), ZoneInfo(settings.timezone)),
        "note": "",
    }
    return _page(request, templates, db, user, settings, values)


@router.post("/hypo", response_model=None)
async def save_hypo(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = {k: str(v) for k, v in (await request.form()).items()}
    zone = ZoneInfo(settings.timezone)
    try:
        saved = log_hypo(db, user, parse_hypo_form(form, zone), now=_now())
    except EntryError as error:
        db.rollback()
        return _page(
            request,
            templates,
            db,
            user,
            settings,
            form,
            error=str(error),
            ask_confirm=isinstance(error, PossibleDuplicate),
            status_code=422,
        )
    db.commit()
    label = TREATMENT_LABELS[saved.treatment].lower()
    if saved.treatment is HypoTreatmentKind.GLUCAGON:
        request.session["flash"] = GLUCAGON_MESSAGE
    else:
        request.session["flash"] = (
            f"Saved {label} at {saved.treated_at.astimezone(zone):%H:%M}."
            f" Check your glucose again in {RECHECK_MINUTES} minutes."
        )
    return RedirectResponse("/log/hypo", status_code=303)
