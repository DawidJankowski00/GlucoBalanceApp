"""The live CGM view (/live) and the CGM connection settings (/settings/cgm)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.cgm.base import CGMError
from glucobalance.cgm.crypto import SecretKeyError
from glucobalance.cgm.librelinkup import SERVERS, LluPatient
from glucobalance.cgm_service import (
    CGMRuntime,
    CGMSettingsError,
    LibreLinkUpInput,
    get_connection,
    list_patients,
    live_status,
    poll_connection,
    save_librelinkup,
    use_simulator,
)
from glucobalance.features import feature_flags
from glucobalance.forecast.models import Forecaster
from glucobalance.forecast_service import low_soon
from glucobalance.models import CGMSourceKind, GlucoseReading, Trend, User, UserSettings
from glucobalance.units import format_glucose
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()

# U+FE0E asks for the plain text arrow, not the coloured emoji some phones draw.
_TEXT = "︎"
ARROWS = {
    Trend.FALLING_FAST: ("↓" + _TEXT, "falling fast"),
    Trend.FALLING: ("↘" + _TEXT, "falling"),
    Trend.STEADY: ("→" + _TEXT, "steady"),
    Trend.RISING: ("↗" + _TEXT, "rising"),
    Trend.RISING_FAST: ("↑" + _TEXT, "rising fast"),
}
POLL_CHOICES = (1, 2, 3, 4, 5)
SPARK_WIDTH, SPARK_HEIGHT = 300, 80
SPARK_MIN, SPARK_MAX = 40, 300
LIVE_HOURS = 3


def _now() -> datetime:
    return datetime.now(UTC)


def _runtime(request: Request) -> CGMRuntime:
    runtime: CGMRuntime = request.app.state.cgm_runtime
    return runtime


def _minutes_ago(moment: datetime, now: datetime) -> str:
    minutes = max(int((now - moment).total_seconds() // 60), 0)
    if minutes == 0:
        return "just now"
    if minutes < 120:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago"


def _y(mgdl: float) -> float:
    clamped = min(max(mgdl, SPARK_MIN), SPARK_MAX)
    return round(SPARK_HEIGHT - (clamped - SPARK_MIN) / (SPARK_MAX - SPARK_MIN) * SPARK_HEIGHT, 1)


def sparkline(
    readings: Sequence[GlucoseReading], start: datetime, end: datetime, low: int, high: int
) -> dict[str, object]:
    """SVG coordinates for the last few hours: the line and the target band."""
    span = (end - start).total_seconds() or 1.0
    points = " ".join(
        f"{round((r.measured_at - start).total_seconds() / span * SPARK_WIDTH, 1)},"
        f"{_y(r.value_mgdl)}"
        for r in readings
    )
    return {
        "points": points,
        "band_top": _y(high),
        "band_height": round(_y(low) - _y(high), 1),
        "width": SPARK_WIDTH,
        "height": SPARK_HEIGHT,
    }


def _forecaster(request: Request) -> Forecaster:
    forecaster: Forecaster = request.app.state.forecaster
    return forecaster


def _live_context(
    db: DbSession, user: User, settings: UserSettings, forecaster: Forecaster
) -> dict[str, Any]:
    now = _now()
    status = live_status(db, user, now=now, hours=LIVE_HOURS)
    zone = ZoneInfo(settings.timezone)
    latest = status.latest
    context: dict[str, Any] = {
        "connection": status.connection,
        "stale": status.stale,
        "latest": None,
        "spark": None,
        "low_soon": low_soon(db, user, forecaster, now=now),
    }
    if latest is not None:
        arrow, words = ARROWS.get(latest.trend, ("", "")) if latest.trend else ("", "")
        level = (
            "low"
            if latest.value_mgdl < settings.target_low_mgdl
            else "high"
            if latest.value_mgdl > settings.target_high_mgdl
            else "in_range"
        )
        context["latest"] = {
            "value": format_glucose(latest.value_mgdl, settings.display_unit),
            "arrow": arrow,
            "trend": words,
            "level": level,
            "when": latest.measured_at.astimezone(zone).strftime("%H:%M"),
            "ago": _minutes_ago(latest.measured_at, now),
        }
    if status.recent:
        context["spark"] = sparkline(
            status.recent,
            now - timedelta(hours=LIVE_HOURS),
            now,
            settings.target_low_mgdl,
            settings.target_high_mgdl,
        )
    return context


@router.get("/live", response_model=None)
def live_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    cgm = feature_flags(settings.delivery_mode, settings.monitoring_mode).cgm_import
    return render(
        request,
        templates,
        "live.html",
        user,
        cgm=cgm,
        **(_live_context(db, user, settings, _forecaster(request)) if cgm else {}),
    )


@router.get("/live/panel", response_model=None)
def live_panel(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    """The part of /live that refreshes itself every minute."""
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    context = _live_context(db, user, settings, _forecaster(request))
    return render(request, templates, "_live_panel.html", user, **context)


# ---------- settings ----------


def _settings_page(
    request: Request,
    templates: Templates,
    db: DbSession,
    user: User,
    settings: UserSettings,
    *,
    patients: Sequence[LluPatient] = (),
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    connection = get_connection(db, user)
    zone = ZoneInfo(settings.timezone)

    def local(moment: datetime | None) -> str | None:
        return moment.astimezone(zone).strftime("%d %b %H:%M") if moment else None

    libre = connection is not None and connection.source is CGMSourceKind.LIBRELINKUP
    return render(
        request,
        templates,
        "settings_cgm.html",
        user,
        status_code=status_code,
        error=error,
        cgm=feature_flags(settings.delivery_mode, settings.monitoring_mode).cgm_import,
        connection=connection,
        libre=libre,
        simulator=connection is not None and connection.source is CGMSourceKind.SIMULATOR,
        servers=SERVERS,
        poll_choices=POLL_CHOICES,
        patients=patients,
        has_key=_runtime(request).box is not None,
        last_success=local(connection.last_success_at) if connection else None,
        retry_after=local(connection.retry_after) if connection else None,
    )


async def _form(request: Request) -> dict[str, str]:
    return {k: str(v) for k, v in (await request.form()).items()}


@router.get("/settings/cgm", response_model=None)
def cgm_settings_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    return _settings_page(request, templates, db, user, settings)


@router.post("/settings/cgm", response_model=None)
async def save_cgm_settings(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    try:
        poll_minutes = int(form.get("poll_minutes", "5"))
    except ValueError:
        poll_minutes = 0
    patient = form.get("patient_id")
    try:
        save_librelinkup(
            db,
            user,
            LibreLinkUpInput(
                enabled="enabled" in form,
                email=form.get("email", ""),
                password=form.get("password") or None,
                server=form.get("server", "io"),
                auto_accept_terms="auto_accept_terms" in form,
                patient_id=patient if patient is not None else None,
                reconnect="reconnect" in form,
                poll_minutes=poll_minutes,
            ),
            _runtime(request).box,
        )
    except CGMSettingsError as error:
        db.rollback()
        return _settings_page(
            request, templates, db, user, settings, error=str(error), status_code=422
        )
    db.commit()
    request.session["flash"] = "LibreLinkUp settings saved."
    return RedirectResponse("/settings/cgm", status_code=303)


@router.post("/settings/cgm/simulator", response_model=None)
async def save_simulator(request: Request, user: CurrentUser, db: DbSession) -> RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    enabled = (await _form(request)).get("enabled") == "on"
    use_simulator(db, user, enabled=enabled)
    db.commit()
    request.session["flash"] = (
        "The simulated CGM is on." if enabled else "The simulated CGM is off."
    )
    return RedirectResponse("/settings/cgm", status_code=303)


@router.post("/settings/cgm/test", response_model=None)
def test_connection(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    """Poll now and, for LibreLinkUp, list the patients so one can be chosen."""
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    connection = get_connection(db, user)
    if connection is None:
        return RedirectResponse("/settings/cgm", status_code=303)
    runtime = _runtime(request)
    now = _now()
    patients: list[LluPatient] = []
    if connection.source is CGMSourceKind.LIBRELINKUP:
        try:
            patients = list_patients(db, connection, runtime, now=now)
        except (CGMError, SecretKeyError) as error:
            connection.last_error = str(error)
            db.commit()
            return _settings_page(
                request, templates, db, user, settings, error=str(error), status_code=422
            )
    added = poll_connection(db, connection, runtime, now=now)
    db.commit()
    if connection.last_error:
        return _settings_page(
            request,
            templates,
            db,
            user,
            settings,
            patients=patients,
            error=connection.last_error,
            status_code=422,
        )
    request.session["flash"] = f"Connected. {added} new reading{'s' if added != 1 else ''}."
    return _settings_page(request, templates, db, user, settings, patients=patients)
