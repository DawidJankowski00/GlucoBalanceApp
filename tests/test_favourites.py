"""Favourite meals: saved name and carbs that can be logged again in one tap."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.entries import EntryError, PossibleDuplicate
from glucobalance.favourites import (
    MAX_FAVOURITES,
    add_favourite,
    delete_favourite,
    list_favourites,
    log_favourite,
)
from glucobalance.models import CarbEntry, FavouriteMeal, User

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    return register(session, "ann@example.com", "Ann", "correct horse battery")


def make(session: Session, user: User, name: str = "Porridge", grams: str = "45") -> FavouriteMeal:
    return add_favourite(session, user, name, Decimal(grams))


def test_a_favourite_is_saved(session: Session, user: User) -> None:
    saved = add_favourite(session, user, "  Porridge ", Decimal("45.04"), " with banana ")
    assert saved.id is not None
    assert (saved.name, saved.grams, saved.description) == (
        "Porridge",
        Decimal("45.0"),
        "with banana",
    )
    assert saved.user_id == user.id


def test_blank_description_is_none(session: Session, user: User) -> None:
    assert add_favourite(session, user, "Toast", Decimal(30), "  ").description is None


@pytest.mark.parametrize(
    ("name", "grams", "description", "message"),
    [
        ("", "45", None, "name"),
        ("   ", "45", None, "name"),
        ("x" * 101, "45", None, "100 characters"),
        ("Porridge", "0", None, "between 1 and 300 g"),
        ("Porridge", "301", None, "between 1 and 300 g"),
        ("Porridge", "45", "x" * 201, "200 characters"),
    ],
)
def test_bad_favourites_are_rejected(
    session: Session, user: User, name: str, grams: str, description: str | None, message: str
) -> None:
    with pytest.raises(EntryError, match=message):
        add_favourite(session, user, name, Decimal(grams), description)
    assert session.query(FavouriteMeal).count() == 0


def test_names_are_unique_per_user_ignoring_case(session: Session, user: User) -> None:
    make(session, user, "Porridge")
    with pytest.raises(EntryError, match="already have a favourite called Porridge"):
        make(session, user, "porridge")
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    make(session, other, "Porridge")


def test_there_is_a_limit(session: Session, user: User) -> None:
    for number in range(MAX_FAVOURITES):
        make(session, user, f"Meal {number}")
    with pytest.raises(EntryError, match=f"up to {MAX_FAVOURITES} favourites"):
        make(session, user, "One too many")


def test_favourites_are_listed_by_name_for_their_owner_only(session: Session, user: User) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    for name in ("banana", "Apple", "cereal"):
        make(session, user, name)
    make(session, other, "Secret")
    assert [f.name for f in list_favourites(session, user)] == ["Apple", "banana", "cereal"]


def test_a_favourite_can_be_deleted_by_its_owner_only(session: Session, user: User) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    meal = make(session, user)
    assert delete_favourite(session, other, meal.id) is False
    assert list_favourites(session, user) == [meal]
    assert delete_favourite(session, user, meal.id) is True
    assert list_favourites(session, user) == []
    assert delete_favourite(session, user, meal.id) is False


def test_logging_a_favourite_adds_a_carb_entry_now(session: Session, user: User) -> None:
    meal = add_favourite(session, user, "Porridge", Decimal("45"), "with banana")
    entry = log_favourite(session, user, meal.id, now=NOW)
    assert (entry.grams, entry.description, entry.eaten_at) == (
        Decimal("45.0"),
        "with banana",
        NOW,
    )


def test_a_favourite_without_a_description_logs_its_name(session: Session, user: User) -> None:
    meal = make(session, user, "Porridge")
    assert log_favourite(session, user, meal.id, now=NOW).description == "Porridge"


def test_logging_twice_in_ten_minutes_needs_confirming(session: Session, user: User) -> None:
    meal = make(session, user)
    log_favourite(session, user, meal.id, now=NOW)
    with pytest.raises(PossibleDuplicate):
        log_favourite(session, user, meal.id, now=NOW + timedelta(minutes=5))
    log_favourite(session, user, meal.id, now=NOW + timedelta(minutes=5), confirmed=True)
    assert session.query(CarbEntry).count() == 2


def test_other_peoples_and_missing_favourites_cannot_be_logged(
    session: Session, user: User
) -> None:
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    meal = make(session, other)
    with pytest.raises(EntryError, match="not found"):
        log_favourite(session, user, meal.id, now=NOW)
    with pytest.raises(EntryError, match="not found"):
        log_favourite(session, user, 9999, now=NOW)
    assert session.query(CarbEntry).count() == 0
