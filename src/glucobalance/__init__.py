"""GlucoBalanceApp core package."""

MGDL_PER_MMOLL = 18.0


def mgdl_to_mmoll(mgdl: float) -> float:
    """Convert a glucose reading from mg/dL to mmol/L, rounded to one decimal."""
    return round(mgdl / MGDL_PER_MMOLL, 1)
