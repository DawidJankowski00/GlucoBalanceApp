"""The chart page: a daily or weekly glucose chart drawn by Plotly."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.charts import daily_figure, weekly_figure
from glucobalance.repositories import CarbRepository, GlucoseRepository, InsulinRepository
from glucobalance.timeline import day_bounds
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()

VIEWS = {"day": 1, "week": 7}


def _parse_day(raw: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(raw) if raw else fallback
    except ValueError:
        return fallback


@router.get("/chart", response_model=None)
def chart(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
    day: str | None = None,
    view: str = "day",
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    view = view if view in VIEWS else "day"
    zone = ZoneInfo(settings.timezone)
    today = datetime.now(UTC).astimezone(zone).date()
    shown = min(_parse_day(day, today), today)
    unit = settings.display_unit
    low, high = settings.target_low_mgdl, settings.target_high_mgdl
    if view == "day":
        start, end = day_bounds(shown, zone)
        figure = daily_figure(
            shown,
            zone,
            readings=GlucoseRepository(db).between(user.id, start, end),
            doses=InsulinRepository(db).between(user.id, start, end),
            carbs=CarbRepository(db).between(user.id, start, end),
            unit=unit,
            target_low_mgdl=low,
            target_high_mgdl=high,
        )
        title = "Today" if shown == today else f"{shown:%a %d %b %Y}"
    else:
        start = day_bounds(shown - timedelta(days=6), zone)[0]
        end = day_bounds(shown, zone)[1]
        figure = weekly_figure(
            shown,
            zone,
            readings=GlucoseRepository(db).between(user.id, start, end),
            unit=unit,
            target_low_mgdl=low,
            target_high_mgdl=high,
        )
        title = f"{shown - timedelta(days=6):%d %b} to {shown:%d %b %Y}"
    step = timedelta(days=VIEWS[view])
    return render(
        request,
        templates,
        "chart.html",
        user,
        figure=figure,
        view=view,
        title=title,
        previous=(shown - step).isoformat(),
        next=(shown + step).isoformat() if shown < today else None,
    )
