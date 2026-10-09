"""The home page, the settings page and the settings history."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.features import FeatureFlags, SiteRotationUnit, feature_flags
from glucobalance.models import ChangeSource, DisplayUnit
from glucobalance.settings_service import SettingsError, apply_settings, history, to_input
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.forms import BLOCK_ROWS, parse_settings, settings_to_form
from glucobalance.web.rendering import render

router = APIRouter()

FIELD_LABELS = {
    "delivery_mode": "Insulin delivery",
    "monitoring_mode": "Glucose monitoring",
    "display_unit": "Glucose units",
    "target_low_mgdl": "Low target (mg/dL)",
    "target_high_mgdl": "High target (mg/dL)",
    "insulin_action_minutes": "Insulin action time (minutes)",
    "max_bolus_units": "Maximum bolus (units)",
    "dose_step_units": "Dose step (units)",
    "clinician_contact": "Clinician contact",
    "timezone": "Time zone",
    "site_rest_days": "Site rest period (days)",
    "set_change_days": "Infusion set change (days)",
    "time_blocks": "Carb ratio and sensitivity blocks (mg/dL)",
}
SOURCE_LABELS = {
    ChangeSource.ONBOARDING: "Onboarding",
    ChangeSource.USER: "You",
    ChangeSource.ASSISTANT_SUGGESTION: "Accepted assistant suggestion",
}


def describe_features(flags: FeatureFlags) -> list[tuple[str, str]]:
    """Short plain-language lines about what the app will do for this user's two choices."""
    if flags.site_rotation_unit is SiteRotationUnit.PER_SET_CHANGE:
        sites = "One site per infusion set change."
        reminders = "Reminders for infusion set changes, reservoir refills and pump battery."
        logging = "Log pump set problems such as occlusions."
    else:
        sites = "A new point for every injection, tracked separately for long-acting insulin."
        reminders = "Daily long-acting dose reminder with a missed-dose alert, plus pen needles."
        logging = "Log every injection with its insulin type and site."
    if flags.cgm_import:
        glucose = "Readings arrive automatically from your CGM, with high, low and falling alerts."
        stats = "Time in range, variability and an ambulatory glucose profile."
    else:
        glucose = "Log meter readings quickly with a tag such as fasting or before meal."
        stats = "Averages by time of day, with a warning when there is little data."
    return [
        ("Site rotation", sites),
        ("Insulin reminders", reminders),
        ("Insulin logging", logging),
        ("Glucose data", glucose),
        ("Statistics", stats),
    ]


@router.get("/", response_model=None)
def home(
    request: Request, user: CurrentUser, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    flags = feature_flags(user.settings.delivery_mode, user.settings.monitoring_mode)
    return render(request, templates, "home.html", user, features=describe_features(flags))


@router.get("/settings", response_model=None)
def settings_page(
    request: Request, user: CurrentUser, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    return _settings_page(request, templates, user, settings_to_form(to_input(user.settings)))


@router.post("/settings", response_model=None)
async def save_settings(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = {k: str(v) for k, v in (await request.form()).items()}
    try:
        data = parse_settings(form)
        apply_settings(db, user, data, ChangeSource.USER, user)
    except SettingsError as error:
        db.rollback()
        return _settings_page(request, templates, user, form, error=str(error), status_code=422)
    db.commit()
    request.session["flash"] = "Settings saved."
    return RedirectResponse("/settings", status_code=303)


@router.get("/settings/history", response_class=HTMLResponse)
def settings_history(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse:
    changes = [
        {
            "when": change.changed_at,
            "field": FIELD_LABELS.get(change.field, change.field),
            "old": change.old_value,
            "new": change.new_value,
            "source": SOURCE_LABELS[change.source],
            "by": user.display_name if change.changed_by_id == user.id else "System",
        }
        for change in history(db, user)
    ]
    return render(request, templates, "settings_history.html", user, changes=changes)


def _settings_page(
    request: Request,
    templates: Templates,
    user: CurrentUser,
    values: dict[str, str],
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return render(
        request,
        templates,
        "settings.html",
        user,
        status_code=status_code,
        values=values,
        rows=range(BLOCK_ROWS),
        unit_is_mmol=values.get("display_unit") == DisplayUnit.MMOLL.value,
        error=error,
    )
