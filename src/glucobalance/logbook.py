"""The logbook: every entry in a date range, filtered and paged, and its CSV export.

Dates are the user's local days and the end date is included. Entries are merged by
``timeline.load_range``; filtering and paging happen here, in plain Python.
"""

import csv
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.models import (
    CarbEntry,
    DisplayUnit,
    GlucoseReading,
    GlucoseTag,
    InsulinDose,
    Note,
)
from glucobalance.timeline import EntryKind, TimelineItem, day_bounds, load_range
from glucobalance.units import mgdl_to_mmoll

PAGE_SIZE = 50
DEFAULT_DAYS = 14
MAX_RANGE_DAYS = 366

CSV_COLUMNS = (
    "utc_time",
    "local_time",
    "type",
    "glucose_mgdl",
    "glucose_display",
    "display_unit",
    "insulin_units",
    "insulin_kind",
    "insulin_type",
    "carbs_g",
    "tag",
    "note",
)
# A spreadsheet runs a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class LogbookError(ValueError):
    """The filters are not acceptable. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class LogbookFilters:
    start: date
    end: date
    kinds: frozenset[EntryKind]
    tag: GlucoseTag | None = None


@dataclass(frozen=True, slots=True)
class LogbookPage:
    rows: list[TimelineItem]
    page: int
    pages: int
    total: int


def _date(raw: str, default: date) -> date:
    raw = raw.strip()
    if not raw:
        return default
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise LogbookError("Enter dates as YYYY-MM-DD.") from None


def _kinds(raw: str) -> frozenset[EntryKind]:
    names = [name.strip() for name in raw.split(",") if name.strip()]
    if not names:
        return frozenset(EntryKind)
    try:
        return frozenset(EntryKind(name) for name in names)
    except ValueError:
        choices = ", ".join(kind.value for kind in EntryKind)
        raise LogbookError(f"Choose entry types from the list: {choices}.") from None


def _tag(raw: str) -> GlucoseTag | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return GlucoseTag(raw)
    except ValueError:
        raise LogbookError("Choose a tag from the list.") from None


def parse_filters(params: Mapping[str, str], today: date) -> LogbookFilters:
    """Read the filters from a query string. Missing or blank values mean no filter."""
    end = _date(params.get("end", ""), today)
    start = _date(params.get("start", ""), end - timedelta(days=DEFAULT_DAYS - 1))
    if start > end:
        raise LogbookError("The start date must be before the end date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise LogbookError("Choose a range of one year or less.")
    return LogbookFilters(
        start=start, end=end, kinds=_kinds(params.get("type", "")), tag=_tag(params.get("tag", ""))
    )


def query_logbook(
    session: Session,
    user_id: int,
    zone: ZoneInfo,
    filters: LogbookFilters,
    *,
    page: int = 1,
    page_size: int | None = PAGE_SIZE,
) -> LogbookPage:
    """The matching entries, newest first. ``page_size=None`` returns all of them."""
    start = day_bounds(filters.start, zone)[0]
    end = day_bounds(filters.end, zone)[1]
    # A tag belongs to glucose readings only, so filtering by tag leaves nothing else.
    kinds = filters.kinds & {EntryKind.GLUCOSE} if filters.tag else filters.kinds
    items = load_range(session, user_id, start, end, kinds)
    if filters.tag:
        items = [
            i for i in items if isinstance(i.entry, GlucoseReading) and i.entry.tag is filters.tag
        ]
    items.reverse()
    if page_size is None:
        return LogbookPage(items, 1, 1, len(items))
    pages = max(1, math.ceil(len(items) / page_size))
    page = min(max(page, 1), pages)
    first = (page - 1) * page_size
    return LogbookPage(items[first : first + page_size], page, pages, len(items))


def _safe(text: str | None) -> str:
    if not text:
        return ""
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def _units(value: object) -> str:
    return format(value.normalize(), "f")  # type: ignore[attr-defined]


def _csv_row(item: TimelineItem, unit: DisplayUnit, zone: ZoneInfo) -> dict[str, str]:
    row = dict.fromkeys(CSV_COLUMNS, "")
    row["utc_time"] = item.at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    row["local_time"] = f"{item.at.astimezone(zone):%Y-%m-%d %H:%M}"
    row["type"] = item.kind.value
    entry = item.entry
    if isinstance(entry, GlucoseReading):
        row["glucose_mgdl"] = str(entry.value_mgdl)
        row["glucose_display"] = (
            f"{mgdl_to_mmoll(entry.value_mgdl):.1f}"
            if unit is DisplayUnit.MMOLL
            else str(entry.value_mgdl)
        )
        row["display_unit"] = unit.value
        row["tag"] = entry.tag.value if entry.tag else ""
        row["note"] = _safe(entry.note)
    elif isinstance(entry, InsulinDose):
        row["insulin_units"] = _units(entry.units)
        row["insulin_kind"] = entry.kind.value
        row["insulin_type"] = entry.insulin_type.value
    elif isinstance(entry, CarbEntry):
        row["carbs_g"] = _units(entry.grams)
        row["note"] = _safe(entry.description)
    else:
        assert isinstance(entry, Note)
        row["note"] = _safe(entry.text)
    return row


def to_csv(rows: Sequence[TimelineItem], unit: DisplayUnit, zone: ZoneInfo) -> str:
    """CSV text for ``rows`` as ``query_logbook`` returns them (newest first), oldest first."""
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(_csv_row(item, unit, zone) for item in reversed(rows))
    return out.getvalue()
