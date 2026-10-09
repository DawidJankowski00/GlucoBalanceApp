"""Favourite meals: a saved name and carbs that can be logged again in one tap."""

from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError
from glucobalance.models import CarbEntry, FavouriteMeal, User
from glucobalance.repositories import FavouriteRepository
from glucobalance.treatment_service import (
    DESCRIPTION_MAX_LENGTH,
    MAX_CARBS,
    MIN_CARBS,
    CarbInput,
    log_carbs,
)

MAX_FAVOURITES = 50
NAME_MAX_LENGTH = 100


def add_favourite(
    session: Session,
    user: User,
    name: str,
    grams: Decimal,
    description: str | None = None,
) -> FavouriteMeal:
    """Check and save a favourite meal. Never commits."""
    name = name.strip()
    if not name:
        raise EntryError("Give the meal a name to save it as a favourite.")
    if len(name) > NAME_MAX_LENGTH:
        raise EntryError(f"Keep the name under {NAME_MAX_LENGTH} characters.")
    grams = grams.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if not MIN_CARBS <= grams <= MAX_CARBS:
        raise EntryError("Enter carbs between 1 and 300 g.")
    description = (description or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        raise EntryError(f"Keep the description under {DESCRIPTION_MAX_LENGTH} characters.")
    repository = FavouriteRepository(session)
    existing = repository.find_by_name(user.id, name)
    if existing is not None:
        raise EntryError(f"You already have a favourite called {existing.name}.")
    if repository.count(user.id) >= MAX_FAVOURITES:
        raise EntryError(f"You can keep up to {MAX_FAVOURITES} favourites. Delete one first.")
    return repository.add(
        FavouriteMeal(user_id=user.id, name=name, grams=grams, description=description)
    )


def list_favourites(session: Session, user: User) -> Sequence[FavouriteMeal]:
    return FavouriteRepository(session).for_user(user.id)


def delete_favourite(session: Session, user: User, favourite_id: int) -> bool:
    """Delete one of the user's own favourites; False if it does not exist or is not theirs."""
    repository = FavouriteRepository(session)
    favourite = repository.get_owned(user.id, favourite_id)
    if favourite is None:
        return False
    repository.delete(favourite)
    return True


def log_favourite(
    session: Session,
    user: User,
    favourite_id: int,
    *,
    now: datetime,
    confirmed: bool = False,
) -> CarbEntry:
    """Log a favourite meal as eaten ``now``, with the usual double-entry check."""
    favourite = FavouriteRepository(session).get_owned(user.id, favourite_id)
    if favourite is None:
        raise EntryError("That favourite meal was not found.")
    return log_carbs(
        session,
        user,
        CarbInput(
            grams=favourite.grams,
            eaten_at=now,
            description=favourite.description or favourite.name,
            confirmed=confirmed,
        ),
        now=now,
    )
