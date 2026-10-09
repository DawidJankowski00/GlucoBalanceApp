"""Logging glucose readings by hand: the checks a reading must pass before it is saved.

``log_reading`` validates first and then saves through the repository, like
``settings_service.apply_settings``. Every problem is raised as ``entries.EntryError`` with a
message that can be shown on the page. Values are in mg/dL; the form converts mmol/L first.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError, check_entry_time
from glucobalance.models import GlucoseReading, GlucoseTag, ReadingSource, User
from glucobalance.repositories import GlucoseRepository

# What home meters can display; below or above they show LO or HI instead of a number.
MIN_MGDL = 20
MAX_MGDL = 600
LOW_MGDL = 70
# The same value again this soon is almost always the same reading saved twice.
DOUBLE_TAP_WINDOW = timedelta(minutes=5)
NOTE_MAX_LENGTH = 500


@dataclass(frozen=True, slots=True)
class GlucoseEntry:
    value_mgdl: int
    measured_at: datetime
    tag: GlucoseTag | None = None
    note: str | None = None


def is_low(value_mgdl: int) -> bool:
    """Below 70 mg/dL (3.9 mmol/L): a hypo that needs treating."""
    return value_mgdl < LOW_MGDL


def suggest_tag(local: time) -> GlucoseTag | None:
    """A likely tag for a reading taken at ``local`` (the user's wall-clock time).

    Before and after meals depend on when the user eats, so daytime readings get no guess.
    """
    if time(5, 0) <= local < time(9, 0):
        return GlucoseTag.FASTING
    if local >= time(22, 0) or local < time(2, 0):
        return GlucoseTag.BEDTIME
    if time(2, 0) <= local < time(5, 0):
        return GlucoseTag.NIGHT
    return None


def _clean_note(note: str | None) -> str | None:
    if note is None or not note.strip():
        return None
    note = note.strip()
    if len(note) > NOTE_MAX_LENGTH:
        raise EntryError(f"Keep the note under {NOTE_MAX_LENGTH} characters.")
    return note


def _check_value(value_mgdl: int) -> None:
    if not MIN_MGDL <= value_mgdl <= MAX_MGDL:
        raise EntryError(
            f"Enter a glucose value between {MIN_MGDL} and {MAX_MGDL} mg/dL (1.1 to 33.3 mmol/L)."
        )


def _check_duplicates(entry: GlucoseEntry, nearby: Sequence[GlucoseReading]) -> None:
    """``nearby`` holds the user's manual readings within the double-tap window."""
    minute = entry.measured_at.replace(second=0, microsecond=0)
    for reading in nearby:
        if reading.measured_at.replace(second=0, microsecond=0) == minute:
            raise EntryError("You already logged a reading at that time.")
        if reading.value_mgdl == entry.value_mgdl:
            raise EntryError(
                "The same value was logged less than 5 minutes ago. It is probably saved already."
            )


def _nearby_manual(session: Session, user: User, at: datetime) -> list[GlucoseReading]:
    start = at - DOUBLE_TAP_WINDOW
    end = at + DOUBLE_TAP_WINDOW + timedelta(microseconds=1)  # ranges are half-open
    return [
        r
        for r in GlucoseRepository(session).between(user.id, start, end)
        if r.source is ReadingSource.MANUAL
    ]


def log_reading(
    session: Session, user: User, entry: GlucoseEntry, *, now: datetime
) -> GlucoseReading:
    """Check ``entry`` and save it as a manual reading. Never commits."""
    _check_value(entry.value_mgdl)
    check_entry_time(entry.measured_at, now)
    note = _clean_note(entry.note)
    _check_duplicates(entry, _nearby_manual(session, user, entry.measured_at))
    return GlucoseRepository(session).add(
        GlucoseReading(
            user_id=user.id,
            measured_at=entry.measured_at,
            value_mgdl=entry.value_mgdl,
            source=ReadingSource.MANUAL,
            tag=entry.tag,
            note=note,
        )
    )


def recent_readings(session: Session, user: User, *, limit: int = 5) -> Sequence[GlucoseReading]:
    """The user's latest readings of any source, newest first."""
    return GlucoseRepository(session).recent(user.id, limit)
