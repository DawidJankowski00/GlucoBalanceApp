"""The weekly review: stored suggestions, at most three, each accepted or rejected by the user."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.adjustment_service import SuggestionError
from glucobalance.adjustments import Setting, Suggestion
from glucobalance.models import ChangeSource, SuggestionStatus, User
from glucobalance.patterns import PatternKind
from glucobalance.settings_service import apply_settings, history
from glucobalance.weekly_review import (
    MAX_SUGGESTIONS,
    accept,
    pending,
    recent_decisions,
    reject,
    run_review,
    save_suggestions,
    to_suggestion,
)
from test_adjustment_service import NOW, add_night_lows, backdate
from test_settings_service import make_input


@pytest.fixture
def user(session: Session) -> User:
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    backdate(session, NOW - timedelta(days=60))
    return user


def isf(proposed: int, start: time = time(0, 0)) -> Suggestion:
    return Suggestion(
        PatternKind.NIGHT_LOWS, start, Setting.ISF, Decimal(40), Decimal(proposed), "Night lows."
    )


def test_a_review_without_patterns_has_no_suggestions(session: Session, user: User) -> None:
    review = run_review(session, user, now=NOW)
    assert review.suggestions == []
    assert review.analytics.days == 14


def test_a_review_stores_the_suggestions_as_pending(session: Session, user: User) -> None:
    add_night_lows(session, user)
    review = run_review(session, user, now=NOW)
    [row] = review.suggestions
    assert row.status is SuggestionStatus.PENDING
    stored = to_suggestion(row)
    assert (stored.setting, stored.current, stored.proposed) == (
        Setting.ISF,
        Decimal(40),
        Decimal(44),
    )
    assert pending(session, user) == [row]


def test_running_the_review_again_does_not_duplicate(session: Session, user: User) -> None:
    add_night_lows(session, user)
    first = run_review(session, user, now=NOW).suggestions
    second = run_review(session, user, now=NOW).suggestions
    assert [r.id for r in first] == [r.id for r in second]
    assert len(pending(session, user)) == 1


def test_pending_suggestions_the_data_no_longer_supports_are_dropped(
    session: Session, user: User
) -> None:
    save_suggestions(session, user, [isf(44)], now=NOW)
    assert run_review(session, user, now=NOW).suggestions == []
    assert pending(session, user) == []


def test_at_most_three_suggestions_are_stored(session: Session, user: User) -> None:
    many = [isf(44, time(h, 0)) for h in range(5)]
    assert len(save_suggestions(session, user, many, now=NOW)) == MAX_SUGGESTIONS
    assert len(pending(session, user)) == MAX_SUGGESTIONS


def test_a_changed_suggestion_replaces_the_old_pending_one(session: Session, user: User) -> None:
    save_suggestions(session, user, [isf(44)], now=NOW)
    save_suggestions(session, user, [isf(43)], now=NOW)
    [row] = pending(session, user)
    assert row.proposed_value == Decimal(43)


def test_accepting_changes_the_setting_and_records_the_decision(
    session: Session, user: User
) -> None:
    add_night_lows(session, user)
    [row] = run_review(session, user, now=NOW).suggestions
    accept(session, user, row.id, now=NOW)
    assert row.status is SuggestionStatus.ACCEPTED
    assert row.resolved_at == NOW
    assert user.settings is not None
    assert user.settings.time_blocks[0].isf_mgdl == 44
    assert history(session, user)[0].source is ChangeSource.ASSISTANT_SUGGESTION
    assert recent_decisions(session, user) == [row]


def test_rejecting_leaves_the_settings_alone(session: Session, user: User) -> None:
    add_night_lows(session, user)
    [row] = run_review(session, user, now=NOW).suggestions
    reject(session, user, row.id, now=NOW)
    assert row.status is SuggestionStatus.REJECTED
    assert user.settings is not None
    assert user.settings.time_blocks[0].isf_mgdl == 40
    assert pending(session, user) == []


def test_a_decided_suggestion_cannot_be_decided_again(session: Session, user: User) -> None:
    [row] = save_suggestions(session, user, [isf(44)], now=NOW)
    reject(session, user, row.id, now=NOW)
    with pytest.raises(SuggestionError, match="already been decided"):
        accept(session, user, row.id, now=NOW)


def test_another_users_suggestion_cannot_be_accepted(session: Session, user: User) -> None:
    [row] = save_suggestions(session, user, [isf(44)], now=NOW)
    other = register(session, "bob@example.com", "Bob", "correct horse battery")
    with pytest.raises(SuggestionError, match="does not exist"):
        accept(session, other, row.id, now=NOW)


def test_an_out_of_date_suggestion_stays_pending_when_accept_fails(
    session: Session, user: User
) -> None:
    [row] = save_suggestions(session, user, [isf(44)], now=NOW)
    row.current_value = Decimal(35)  # the setting is 40 now, so the suggestion is stale
    with pytest.raises(SuggestionError):
        accept(session, user, row.id, now=NOW)
    assert row.status is SuggestionStatus.PENDING
