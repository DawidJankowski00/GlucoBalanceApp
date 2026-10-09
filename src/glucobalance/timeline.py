"""One day of readings, doses, carbs and notes merged into a single list.

``build_timeline`` is a pure function; ``load_day`` reads the four tables for one local day.
A "day" runs from local midnight to the next local midnight, so it lasts 23 or 25 hours on
the days the clocks change.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.models import CarbEntry, GlucoseReading, InsulinDose, Note
from glucobalance.repositories import (
    CarbRepository,
    GlucoseRepository,
    InsulinRepository,
    NoteRepository,
)

type Entry = GlucoseReading | InsulinDose | CarbEntry | Note


class EntryKind(StrEnum):
    GLUCOSE = "glucose"
    CARBS = "carbs"
    INSULIN = "insulin"
    NOTE = "note"


# At the same moment: the reading comes first, then the meal, then the dose for it.
_ORDER = {kind: index for index, kind in enumerate(EntryKind)}


@dataclass(frozen=True, slots=True)
class TimelineItem:
    at: datetime
    kind: EntryKind
    entry: Entry


def build_timeline(
    *,
    readings: Iterable[GlucoseReading],
    doses: Iterable[InsulinDose],
    carbs: Iterable[CarbEntry],
    notes: Iterable[Note],
) -> list[TimelineItem]:
    items = [
        *(TimelineItem(r.measured_at, EntryKind.GLUCOSE, r) for r in readings),
        *(TimelineItem(d.taken_at, EntryKind.INSULIN, d) for d in doses),
        *(TimelineItem(c.eaten_at, EntryKind.CARBS, c) for c in carbs),
        *(TimelineItem(n.noted_at, EntryKind.NOTE, n) for n in notes),
    ]
    return sorted(items, key=lambda item: (item.at, _ORDER[item.kind]))


def day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The UTC start and end (exclusive) of ``day`` as lived in ``zone``."""
    start = datetime.combine(day, time(0, 0), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def load_range(
    session: Session,
    user_id: int,
    start: datetime,
    end: datetime,
    kinds: Collection[EntryKind] = frozenset(EntryKind),
) -> list[TimelineItem]:
    """The timeline between two UTC moments (``start`` included, ``end`` excluded).

    Only the tables for the requested ``kinds`` are read.
    """
    return build_timeline(
        readings=GlucoseRepository(session).between(user_id, start, end)
        if EntryKind.GLUCOSE in kinds
        else [],
        doses=InsulinRepository(session).between(user_id, start, end)
        if EntryKind.INSULIN in kinds
        else [],
        carbs=CarbRepository(session).between(user_id, start, end)
        if EntryKind.CARBS in kinds
        else [],
        notes=NoteRepository(session).between(user_id, start, end)
        if EntryKind.NOTE in kinds
        else [],
    )


def load_day(session: Session, user_id: int, day: date, zone: ZoneInfo) -> list[TimelineItem]:
    start, end = day_bounds(day, zone)
    return load_range(session, user_id, start, end)
