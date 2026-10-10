"""Insulin on board (IOB): how much of the rapid insulin already taken is still working.

A pure function, like ``rotation.rank_sites``: it reads only its arguments, so every rule can
be tested with plain values. The model is linear (ADR 0017): a dose counts in full when it is
taken and falls in a straight line to nothing at the end of the insulin action time. Real
insulin acts on a curve, peaking after about an hour; the straight line overstates IOB early
on and understates it late, which is the usual, well-understood trade-off of simple pump
calculators.
"""

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from glucobalance.models import DoseKind, InsulinDose, InsulinType


def counts_for_iob(dose: InsulinDose) -> bool:
    """Only rapid boluses and corrections count. Basal is already covered by the settings."""
    return dose.insulin_type is InsulinType.RAPID and dose.kind is not DoseKind.BASAL


def insulin_on_board(doses: Iterable[InsulinDose], now: datetime, action_minutes: int) -> Decimal:
    """Units still active at ``now``. Doses after ``now`` or older than the action time add 0."""
    if action_minutes <= 0:
        raise ValueError("The insulin action time must be positive.")
    action_seconds = Decimal(action_minutes * 60)
    total = Decimal(0)
    for dose in doses:
        if not counts_for_iob(dose):
            continue
        elapsed = Decimal((now - dose.taken_at).total_seconds())
        if elapsed < 0 or elapsed >= action_seconds:
            continue
        total += dose.units * (1 - elapsed / action_seconds)
    return total
