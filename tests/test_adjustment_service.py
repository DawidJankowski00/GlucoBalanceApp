"""Suggestions from stored data, and accepting one through the settings change log."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.adjustment_service import (
    SuggestionError,
    accept_suggestion,
    recent_changes,
    suggestions_for,
)
from glucobalance.adjustments import Setting, Suggestion
from glucobalance.models import (
    ChangeSource,
    GlucoseReading,
    ReadingSource,
    SettingsChange,
    User,
)
from glucobalance.patterns import PatternKind
from glucobalance.settings_service import TimeBlockInput, apply_settings, history
from test_settings_service import make_input

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(session: Session) -> User:
    """One block from midnight, ICR 10 and ISF 40, set up two months ago."""
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    backdate(session, NOW - timedelta(days=60))
    return user


def backdate(session: Session, at: datetime) -> None:
    session.execute(update(SettingsChange).values(changed_at=at))
    session.flush()
    session.expire_all()


def add_night_lows(session: Session, user: User, nights: int = 4) -> None:
    for day in range(1, nights + 1):
        session.add(
            GlucoseReading(
                user_id=user.id,
                measured_at=NOW.replace(hour=3) - timedelta(days=day),
                value_mgdl=60,
                source=ReadingSource.CGM,
            )
        )
    session.flush()


def night_lows_suggestion(session: Session, user: User) -> Suggestion:
    add_night_lows(session, user)
    [suggestion] = suggestions_for(session, user, now=NOW)
    return suggestion


def test_no_patterns_no_suggestions(session: Session, user: User) -> None:
    assert suggestions_for(session, user, now=NOW) == []


def test_night_lows_give_a_capped_isf_suggestion(session: Session, user: User) -> None:
    s = night_lows_suggestion(session, user)
    assert (s.pattern, s.setting, s.current, s.proposed) == (
        PatternKind.NIGHT_LOWS,
        Setting.ISF,
        Decimal(40),
        Decimal(44),
    )


def test_accepting_saves_through_the_change_log(session: Session, user: User) -> None:
    accept_suggestion(session, user, night_lows_suggestion(session, user), now=NOW)
    assert user.settings is not None
    assert user.settings.time_blocks[0].isf_mgdl == 44
    latest = history(session, user)[0]
    assert latest.source is ChangeSource.ASSISTANT_SUGGESTION
    assert latest.field == "time_blocks"


def test_after_accepting_the_setting_is_frozen(session: Session, user: User) -> None:
    s = night_lows_suggestion(session, user)
    accept_suggestion(session, user, s, now=NOW)
    backdate(session, NOW)
    later = NOW + timedelta(days=1)
    assert suggestions_for(session, user, now=later) == []
    again = replace(s, current=s.proposed, proposed=Decimal(48))
    with pytest.raises(SuggestionError, match="already changed"):
        accept_suggestion(session, user, again, now=later)


def test_a_stale_suggestion_is_rejected(session: Session, user: User) -> None:
    s = Suggestion(PatternKind.NIGHT_LOWS, time(0), Setting.ISF, Decimal(35), Decimal(38), "r")
    with pytest.raises(SuggestionError, match="has changed"):
        accept_suggestion(session, user, s, now=NOW)


def test_a_suggestion_over_the_cap_is_rejected(session: Session, user: User) -> None:
    s = Suggestion(PatternKind.NIGHT_LOWS, time(0), Setting.ISF, Decimal(40), Decimal(60), "r")
    with pytest.raises(SuggestionError, match="bigger"):
        accept_suggestion(session, user, s, now=NOW)


def test_a_missing_block_is_rejected(session: Session, user: User) -> None:
    s = Suggestion(PatternKind.NIGHT_LOWS, time(6), Setting.ISF, Decimal(40), Decimal(44), "r")
    with pytest.raises(SuggestionError, match="no longer exists"):
        accept_suggestion(session, user, s, now=NOW)


def test_recent_changes_compares_blocks_one_by_one(session: Session, user: User) -> None:
    data = replace(
        make_input(),
        time_blocks=(
            TimeBlockInput(time(0, 0), Decimal("10"), 45),  # ISF changed
            TimeBlockInput(time(12, 0), Decimal("12"), 50),  # a new block
        ),
    )
    apply_settings(session, user, data, ChangeSource.USER, user)
    found = {(c.block_start, c.setting) for c in recent_changes(history(session, user)[:1])}
    assert found == {(time(0), Setting.ISF), (time(12), Setting.ICR), (time(12), Setting.ISF)}
