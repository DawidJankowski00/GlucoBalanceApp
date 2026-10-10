"""Gathers what the bolus calculator needs from the database and runs the safety rules first.

This is the only path from stored data to a dose number. It reads, never writes, and never
logs a dose: the user takes (or skips) the dose and logs it as usual.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.bolus import BolusResult, calculate_bolus
from glucobalance.dosing_safety import Refusal, RefusalReason, block_at, check_glucose
from glucobalance.iob import insulin_on_board
from glucobalance.models import User
from glucobalance.repositories import GlucoseRepository, InsulinRepository

MAX_CARBS_G = Decimal(300)  # the same limit as a logged carb entry


@dataclass(frozen=True, slots=True)
class BolusAdvice:
    """A dose number and every input that went into it, so the user can check the sum."""

    result: BolusResult
    glucose_mgdl: int
    reading_at: datetime
    target_mgdl: int
    icr: Decimal
    isf_mgdl: int
    block_start: time


def correction_target(low_mgdl: int, high_mgdl: int) -> int:
    """The glucose a correction aims for: the middle of the target range, rounded down."""
    return (low_mgdl + high_mgdl) // 2


def advise_bolus(
    session: Session, user: User, carbs_g: Decimal, *, now: datetime
) -> BolusAdvice | Refusal:
    """A suggested bolus for ``carbs_g`` grams now, or the reason none can be given."""
    if not Decimal(0) <= carbs_g <= MAX_CARBS_G:
        raise ValueError("The carbs must be between 0 and 300 g.")
    settings = user.settings
    if settings is None or not settings.time_blocks:
        return Refusal(RefusalReason.NO_SETTINGS, "Set your carb ratio and sensitivity first.")

    reading = GlucoseRepository(session).latest(user.id)
    refusal = check_glucose(reading, now)
    if refusal is not None:
        return refusal
    assert reading is not None  # check_glucose refuses a missing reading

    local = now.astimezone(ZoneInfo(settings.timezone)).time()
    block = block_at(list(settings.time_blocks), local)
    if block is None:
        return Refusal(RefusalReason.NO_SETTINGS, "No carb ratio covers this time of day.")

    action = settings.insulin_action_minutes
    doses = InsulinRepository(session).between(
        user.id, now - timedelta(minutes=action), now + timedelta(seconds=1)
    )
    target = correction_target(settings.target_low_mgdl, settings.target_high_mgdl)
    result = calculate_bolus(
        carbs_g=carbs_g,
        glucose_mgdl=reading.value_mgdl,
        target_mgdl=target,
        icr=block.icr_grams_per_unit,
        isf_mgdl=block.isf_mgdl,
        iob_units=insulin_on_board(doses, now, action),
        step=settings.dose_step_units,
        max_bolus=settings.max_bolus_units,
    )
    return BolusAdvice(
        result=result,
        glucose_mgdl=reading.value_mgdl,
        reading_at=reading.measured_at,
        target_mgdl=target,
        icr=block.icr_grams_per_unit,
        isf_mgdl=block.isf_mgdl,
        block_start=block.start_time,
    )
