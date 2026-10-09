"""Turn the logging forms (typed in the user's unit and local time) into entries.

The browser's ``datetime-local`` field sends wall-clock time without a zone, such as
``2026-10-09T14:30``. It is read in the user's time zone and converted to UTC here, so
nothing after this module deals with local time.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from glucobalance.glucose_service import GlucoseEntry, GlucoseEntryError
from glucobalance.models import DisplayUnit, GlucoseTag
from glucobalance.units import mmoll_to_mgdl


def parse_local_datetime(raw: str, zone: ZoneInfo) -> datetime:
    """Read a ``datetime-local`` value in ``zone`` and return it in UTC."""
    try:
        local = datetime.strptime(raw.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise GlucoseEntryError("Enter the time as a date and time.") from None
    return local.replace(tzinfo=zone).astimezone(UTC)


def local_input_value(moment: datetime, zone: ZoneInfo) -> str:
    """The ``datetime-local`` value that shows ``moment`` in ``zone``."""
    return f"{moment.astimezone(zone):%Y-%m-%dT%H:%M}"


def _glucose_mgdl(raw: str, unit: DisplayUnit) -> int:
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        raise GlucoseEntryError("Enter your glucose value as a number.") from None
    if not value.is_finite():
        raise GlucoseEntryError("Enter your glucose value as a number.")
    return round(value) if unit is DisplayUnit.MGDL else mmoll_to_mgdl(float(value))


def _tag(raw: str) -> GlucoseTag | None:
    if not raw:
        return None
    try:
        return GlucoseTag(raw)
    except ValueError:
        raise GlucoseEntryError("Choose a tag from the list.") from None


def parse_glucose_form(form: Mapping[str, str], unit: DisplayUnit, zone: ZoneInfo) -> GlucoseEntry:
    return GlucoseEntry(
        value_mgdl=_glucose_mgdl(form.get("value", ""), unit),
        measured_at=parse_local_datetime(form.get("measured_at", ""), zone),
        tag=_tag(form.get("tag", "").strip()),
        note=form.get("note", "").strip() or None,
    )
