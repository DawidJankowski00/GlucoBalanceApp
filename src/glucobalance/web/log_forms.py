"""Turn the logging forms (typed in the user's unit and local time) into entries.

The browser's ``datetime-local`` field sends wall-clock time without a zone, such as
``2026-10-09T14:30``. It is read in the user's time zone and converted to UTC here, so
nothing after this module deals with local time.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from glucobalance.entries import EntryError
from glucobalance.glucose_service import GlucoseEntry
from glucobalance.hypo_service import HypoInput
from glucobalance.models import DisplayUnit, DoseKind, GlucoseTag, HypoTreatmentKind, InsulinType
from glucobalance.treatment_service import CarbInput, DoseInput
from glucobalance.units import mmoll_to_mgdl


def parse_local_datetime(raw: str, zone: ZoneInfo) -> datetime:
    """Read a ``datetime-local`` value in ``zone`` and return it in UTC."""
    try:
        local = datetime.strptime(raw.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise EntryError("Enter the time as a date and time.") from None
    return local.replace(tzinfo=zone).astimezone(UTC)


def local_input_value(moment: datetime, zone: ZoneInfo) -> str:
    """The ``datetime-local`` value that shows ``moment`` in ``zone``."""
    return f"{moment.astimezone(zone):%Y-%m-%dT%H:%M}"


def _number(raw: str, message: str) -> Decimal:
    """A decimal typed with a dot or a comma."""
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        raise EntryError(message) from None
    if not value.is_finite():
        raise EntryError(message)
    return value


def _glucose_mgdl(raw: str, unit: DisplayUnit) -> int:
    value = _number(raw, "Enter your glucose value as a number.")
    return round(value) if unit is DisplayUnit.MGDL else mmoll_to_mgdl(float(value))


def _tag(raw: str) -> GlucoseTag | None:
    if not raw:
        return None
    try:
        return GlucoseTag(raw)
    except ValueError:
        raise EntryError("Choose a tag from the list.") from None


def parse_glucose_form(form: Mapping[str, str], unit: DisplayUnit, zone: ZoneInfo) -> GlucoseEntry:
    return GlucoseEntry(
        value_mgdl=_glucose_mgdl(form.get("value", ""), unit),
        measured_at=parse_local_datetime(form.get("measured_at", ""), zone),
        tag=_tag(form.get("tag", "").strip()),
        note=form.get("note", "").strip() or None,
    )


def _confirmed(form: Mapping[str, str]) -> bool:
    return bool(form.get("confirmed"))


def parse_dose_form(form: Mapping[str, str], zone: ZoneInfo) -> DoseInput:
    try:
        insulin_type = InsulinType(form.get("insulin_type", ""))
    except ValueError:
        raise EntryError("Choose the insulin: rapid-acting or long-acting.") from None
    try:
        kind = DoseKind(form.get("kind", ""))
    except ValueError:
        raise EntryError("Choose what the dose was for.") from None
    return DoseInput(
        units=_number(form.get("units", ""), "Enter the dose in units."),
        insulin_type=insulin_type,
        kind=kind,
        taken_at=parse_local_datetime(form.get("taken_at", ""), zone),
        confirmed=_confirmed(form),
    )


def parse_carb_form(form: Mapping[str, str], zone: ZoneInfo) -> CarbInput:
    return CarbInput(
        grams=_number(form.get("grams", ""), "Enter the carbs in grams."),
        eaten_at=parse_local_datetime(form.get("eaten_at", ""), zone),
        description=form.get("description", "").strip() or None,
        confirmed=_confirmed(form),
    )


def parse_hypo_form(form: Mapping[str, str], zone: ZoneInfo) -> HypoInput:
    try:
        treatment = HypoTreatmentKind(form.get("treatment", ""))
    except ValueError:
        raise EntryError("Choose what you took.") from None
    raw_grams = form.get("carbs_grams", "").strip()
    return HypoInput(
        treatment=treatment,
        treated_at=parse_local_datetime(form.get("treated_at", ""), zone),
        carbs_grams=_number(raw_grams, "Enter the carbs in grams.") if raw_grams else None,
        note=form.get("note", "").strip() or None,
        confirmed=_confirmed(form),
    )
