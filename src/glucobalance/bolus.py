"""The bolus calculator: ``carbs / ICR + (glucose - target) / ISF - IOB``, rounded and capped.

A pure function with no database and no clock. It never decides whether a dose is safe to
show: ``dosing_safety`` refuses first (low or stale glucose), and only then is this called.
"""

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class BolusResult:
    """The parts of the sum, unrounded, and the final dose.

    ``units`` is a multiple of the dose step, never negative and never above the max bolus.
    ``capped`` is true only when the max bolus cut the dose.
    """

    meal_units: Decimal
    correction_units: Decimal
    iob_units: Decimal
    units: Decimal
    capped: bool


def round_to_step(units: Decimal, step: Decimal) -> Decimal:
    """The nearest multiple of ``step`` (a half step rounds up)."""
    return (units / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def floor_to_step(units: Decimal, step: Decimal) -> Decimal:
    """The largest multiple of ``step`` that is not above ``units``."""
    return (units / step).quantize(Decimal(1), rounding=ROUND_FLOOR) * step


def calculate_bolus(
    *,
    carbs_g: Decimal,
    glucose_mgdl: int,
    target_mgdl: int,
    icr: Decimal,
    isf_mgdl: int,
    iob_units: Decimal,
    step: Decimal,
    max_bolus: Decimal,
) -> BolusResult:
    """Rules (each has a test in ``tests/test_bolus.py``):

    1. Meal part: ``carbs / ICR``.
    2. Correction part: ``(glucose - target) / ISF``, or 0 at or below the target. A glucose
       under the target never shrinks the meal part; a low is refused before this is called.
    3. IOB is taken off the sum, and the result is never below 0.
    4. The result is rounded to the nearest dose step, then held at the max bolus (itself
       rounded down to a whole step). ``capped`` says whether rule 4 cut the dose.
    """
    if carbs_g < 0:
        raise ValueError("The carbs must not be negative.")
    if icr <= 0:
        raise ValueError("The ICR must be positive.")
    if isf_mgdl <= 0:
        raise ValueError("The ISF must be positive.")
    if iob_units < 0:
        raise ValueError("The IOB must not be negative.")
    if step <= 0 or max_bolus <= 0:
        raise ValueError("The dose step and the max bolus must be positive.")

    meal = carbs_g / icr
    correction = max(Decimal(0), Decimal(glucose_mgdl - target_mgdl) / isf_mgdl)
    rounded = round_to_step(max(Decimal(0), meal + correction - iob_units), step)
    cap = floor_to_step(max_bolus, step)
    return BolusResult(
        meal_units=meal,
        correction_units=correction,
        iob_units=iob_units,
        units=min(rounded, cap),
        capped=rounded > cap,
    )
