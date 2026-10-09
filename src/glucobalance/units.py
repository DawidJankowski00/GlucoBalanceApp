"""Glucose units. Values are stored in mg/dL; mmol/L exists only for display and input."""

from enum import StrEnum

MGDL_PER_MMOLL = 18.0


class DisplayUnit(StrEnum):
    MGDL = "mg/dL"
    MMOLL = "mmol/L"


def mgdl_to_mmoll(mgdl: float) -> float:
    """Convert a glucose reading from mg/dL to mmol/L, rounded to one decimal."""
    return round(mgdl / MGDL_PER_MMOLL, 1)


def mmoll_to_mgdl(mmoll: float) -> int:
    """Convert a glucose reading from mmol/L to whole mg/dL, the unit used for storage."""
    return round(mmoll * MGDL_PER_MMOLL)


def format_glucose(mgdl: int, unit: DisplayUnit) -> str:
    """Format a stored mg/dL value for display in the user's chosen unit."""
    if unit is DisplayUnit.MMOLL:
        return f"{mgdl_to_mmoll(mgdl):.1f} {unit}"
    return f"{mgdl} {unit}"
