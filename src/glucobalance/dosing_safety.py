"""Safety rules that run before any dose number is worked out (design rule 4).

The calculator only answers "how much"; these rules answer "may a number be shown at all".
When one fails the app shows the reason and no number. Each rule is a pure function.
"""

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Protocol

from glucobalance.cgm.alerts import STALE_AFTER
from glucobalance.patterns import LOW_MGDL

__all__ = ["STALE_AFTER", "Refusal", "RefusalReason", "block_at", "check_glucose"]


class RefusalReason(StrEnum):
    NO_SETTINGS = "no_settings"
    NO_READING = "no_reading"
    STALE_READING = "stale_reading"
    LOW_GLUCOSE = "low_glucose"


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why no dose is shown. ``message`` is safe to show to the user."""

    reason: RefusalReason
    message: str


class Reading(Protocol):
    @property
    def measured_at(self) -> datetime: ...

    @property
    def value_mgdl(self) -> int: ...


class Block(Protocol):
    @property
    def start_time(self) -> time: ...


def check_glucose(reading: Reading | None, now: datetime) -> Refusal | None:
    """Refuse without a reading, with one older than ``STALE_AFTER``, or with a low."""
    if reading is None:
        return Refusal(RefusalReason.NO_READING, "Check your glucose first: there is no reading.")
    if now - reading.measured_at > STALE_AFTER:
        minutes = int(STALE_AFTER.total_seconds() // 60)
        return Refusal(
            RefusalReason.STALE_READING,
            f"Your last reading is more than {minutes} minutes old. Check your glucose again.",
        )
    if reading.value_mgdl < LOW_MGDL:
        return Refusal(
            RefusalReason.LOW_GLUCOSE,
            "Your glucose is low. Treat the low first; no bolus is suggested.",
        )
    return None


def block_at[B: Block](blocks: list[B], local: time) -> B | None:
    """The block in force at ``local``: the last one that starts at or before it."""
    current: B | None = None
    for block in sorted(blocks, key=lambda b: b.start_time):
        if block.start_time <= local:
            current = block
    return current
