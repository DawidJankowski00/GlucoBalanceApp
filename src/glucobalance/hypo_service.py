"""The hypo log: what was taken to treat a low, linked to the reading and to the carbs.

A treatment with carbs also becomes a carb entry, so it shows on the timeline and in the
logbook with everything else eaten. This records what the user did; it never says what to
take or how much. The app only repeats the steps the user's own diabetes team has agreed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError, PossibleDuplicate, check_entry_time
from glucobalance.models import HypoTreatment, HypoTreatmentKind, User
from glucobalance.repositories import GlucoseRepository, HypoRepository
from glucobalance.treatment_service import CarbInput, log_carbs

MAX_CARBS_GRAMS = Decimal(100)
NOTE_MAX_LENGTH = 500
# A reading counts as the low being treated if it was taken this long before.
READING_WINDOW = timedelta(minutes=30)
DUPLICATE_WINDOW = timedelta(minutes=10)
RECHECK_MINUTES = 15


@dataclass(frozen=True, slots=True)
class HypoInput:
    treatment: HypoTreatmentKind
    treated_at: datetime
    carbs_grams: Decimal | None = None
    note: str | None = None
    confirmed: bool = False


def _label(kind: HypoTreatmentKind) -> str:
    return kind.value.replace("_", " ")


def _check(entry: HypoInput) -> Decimal | None:
    """Validate the input and return the carbs rounded to a tenth, or None."""
    grams = entry.carbs_grams
    if entry.treatment is HypoTreatmentKind.GLUCAGON:
        if grams is not None:
            raise EntryError("Glucagon has no carbs. Leave the carbs empty.")
        return None
    if grams is None:
        return None
    grams = grams.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if not Decimal(1) <= grams <= MAX_CARBS_GRAMS:
        raise EntryError("Enter carbs between 1 and 100 g, or leave them empty.")
    return grams


def log_hypo(session: Session, user: User, entry: HypoInput, *, now: datetime) -> HypoTreatment:
    """Check and save a hypo treatment (and its carbs). Never commits."""
    check_entry_time(entry.treated_at, now)
    grams = _check(entry)
    note = (entry.note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX_LENGTH:
        raise EntryError(f"Keep the note under {NOTE_MAX_LENGTH} characters.")

    repository = HypoRepository(session)
    if not entry.confirmed:
        start = entry.treated_at - DUPLICATE_WINDOW
        end = entry.treated_at + DUPLICATE_WINDOW + timedelta(microseconds=1)
        if any(t.treatment is entry.treatment for t in repository.between(user.id, start, end)):
            raise PossibleDuplicate(
                f"You already logged {_label(entry.treatment)} at almost the same time."
                " Tick the box if you took it twice."
            )

    if grams is not None:
        log_carbs(
            session,
            user,
            CarbInput(
                grams=grams,
                eaten_at=entry.treated_at,
                description=f"Hypo treatment: {_label(entry.treatment)}",
                confirmed=True,
            ),
            now=now,
        )
    reading = GlucoseRepository(session).latest_between(
        user.id,
        entry.treated_at - READING_WINDOW,
        entry.treated_at + timedelta(microseconds=1),
    )
    return repository.add(
        HypoTreatment(
            user_id=user.id,
            treated_at=entry.treated_at,
            treatment=entry.treatment,
            carbs_grams=grams,
            reading_id=reading.id if reading else None,
            note=note,
        )
    )


def recent_hypos(session: Session, user: User, *, limit: int = 10) -> Sequence[HypoTreatment]:
    return HypoRepository(session).recent(user.id, limit)
