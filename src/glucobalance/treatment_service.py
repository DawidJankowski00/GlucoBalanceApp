"""Logging insulin doses and carbs by hand: the checks before they are saved.

Only records what the user already did; nothing here suggests or calculates a dose. The
limits come from the user's settings (dose step, maximum bolus), so a typo such as 40 instead
of 4.0 is caught before it reaches the insulin-on-board model in Stage 8.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError, PossibleDuplicate, check_entry_time
from glucobalance.models import CarbEntry, DoseKind, InsulinDose, InsulinType, User
from glucobalance.repositories import CarbRepository, InsulinRepository

MAX_BASAL_UNITS = Decimal(100)
MIN_CARBS = Decimal(1)
MAX_CARBS = Decimal(300)
DESCRIPTION_MAX_LENGTH = 200
# The same dose or meal again this soon is more often a double entry than a second one.
DUPLICATE_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class DoseInput:
    units: Decimal
    insulin_type: InsulinType
    kind: DoseKind
    taken_at: datetime
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class CarbInput:
    grams: Decimal
    eaten_at: datetime
    description: str | None = None
    confirmed: bool = False


def _units(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _window(at: datetime) -> tuple[datetime, datetime]:
    return at - DUPLICATE_WINDOW, at + DUPLICATE_WINDOW + timedelta(microseconds=1)


def _check_dose(dose: DoseInput, user: User) -> None:
    settings = user.settings
    if settings is None:
        raise EntryError("Finish setting up the app before logging insulin.")
    if dose.units <= 0:
        raise EntryError("Enter a dose of more than 0 units.")
    if dose.units % settings.dose_step_units != 0:
        raise EntryError(
            f"Doses go in steps of {_units(settings.dose_step_units)} units. Check the number."
        )
    if dose.kind is DoseKind.BASAL:
        if dose.units > MAX_BASAL_UNITS:
            raise EntryError(f"A basal dose above {MAX_BASAL_UNITS} units cannot be logged.")
        return
    if dose.insulin_type is not InsulinType.RAPID:
        raise EntryError("Boluses and corrections use rapid-acting insulin.")
    if dose.units > settings.max_bolus_units:
        raise EntryError(
            f"That is above your maximum bolus of {_units(settings.max_bolus_units)} units."
            " Check the number, or change the limit in Settings with your diabetes team."
        )


def log_dose(session: Session, user: User, dose: DoseInput, *, now: datetime) -> InsulinDose:
    """Check ``dose`` and save it. Never commits."""
    check_entry_time(dose.taken_at, now)
    _check_dose(dose, user)
    repository = InsulinRepository(session)
    if not dose.confirmed:
        for other in repository.between(user.id, *_window(dose.taken_at)):
            if other.units == dose.units and other.kind is dose.kind:
                raise PossibleDuplicate(
                    f"You already logged {_units(dose.units)} units at almost the same time."
                    " Tick the box if you really took it twice."
                )
    return repository.add(
        InsulinDose(
            user_id=user.id,
            taken_at=dose.taken_at,
            units=dose.units,
            insulin_type=dose.insulin_type,
            kind=dose.kind,
        )
    )


def log_carbs(session: Session, user: User, entry: CarbInput, *, now: datetime) -> CarbEntry:
    """Check ``entry`` and save it. Never commits."""
    check_entry_time(entry.eaten_at, now)
    grams = entry.grams.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if not MIN_CARBS <= grams <= MAX_CARBS:
        raise EntryError("Enter carbs between 1 and 300 g.")
    description = (entry.description or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        raise EntryError(f"Keep the description under {DESCRIPTION_MAX_LENGTH} characters.")
    repository = CarbRepository(session)
    if not entry.confirmed:
        for other in repository.between(user.id, *_window(entry.eaten_at)):
            if other.grams == grams:
                raise PossibleDuplicate(
                    f"You already logged {_units(grams)} g at almost the same time."
                    " Tick the box if this is a second meal."
                )
    return repository.add(
        CarbEntry(user_id=user.id, eaten_at=entry.eaten_at, grams=grams, description=description)
    )
