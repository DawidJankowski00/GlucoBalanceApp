"""The Today page: one local day of readings, doses, carbs and notes in time order."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.models import CarbEntry, GlucoseReading, InsulinDose, Note, UserSettings
from glucobalance.timeline import EntryKind, TimelineItem, load_day
from glucobalance.units import format_glucose
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.log import DOSE_KIND_LABELS, INSULIN_LABELS, TAG_LABELS
from glucobalance.web.rendering import render

router = APIRouter()


def _parse_day(raw: str | None, today: date) -> date:
    if not raw:
        return today
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return today


def describe(item: TimelineItem, settings: UserSettings) -> dict[str, str | bool | None]:
    """What one timeline row shows: a headline and an optional detail line."""
    entry = item.entry
    low = high = False
    detail: str | None = None
    if isinstance(entry, GlucoseReading):
        headline = format_glucose(entry.value_mgdl, settings.display_unit)
        low = entry.value_mgdl < settings.target_low_mgdl
        high = entry.value_mgdl > settings.target_high_mgdl
        parts = [TAG_LABELS[entry.tag] if entry.tag else None, entry.note]
        detail = " · ".join(p for p in parts if p) or None
    elif isinstance(entry, InsulinDose):
        headline = f"{format(entry.units.normalize(), 'f')} units"
        detail = f"{DOSE_KIND_LABELS[entry.kind]}, {INSULIN_LABELS[entry.insulin_type].lower()}"
    elif isinstance(entry, CarbEntry):
        headline = f"{format(entry.grams.normalize(), 'f')} g carbs"
        detail = entry.description
    else:
        assert isinstance(entry, Note)
        headline = entry.text
    return {"headline": headline, "detail": detail, "low": low, "high": high}


@router.get("/today", response_model=None)
def today(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
    day: str | None = None,
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    zone = ZoneInfo(settings.timezone)
    local_today = datetime.now(UTC).astimezone(zone).date()
    shown = _parse_day(day, local_today)
    rows = [
        {
            "time": f"{item.at.astimezone(zone):%H:%M}",
            "kind": item.kind.value,
            **describe(item, settings),
        }
        for item in load_day(db, user.id, shown, zone)
    ]
    return render(
        request,
        templates,
        "today.html",
        user,
        day=shown,
        is_today=shown == local_today,
        previous=(shown - timedelta(days=1)).isoformat(),
        next=(shown + timedelta(days=1)).isoformat() if shown < local_today else None,
        rows=rows,
        kinds=EntryKind,
    )
