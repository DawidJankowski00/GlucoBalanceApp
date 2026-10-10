"""The weekly review: what the last two weeks show, and up to three suggestions to decide on.

The summary and the suggestions come from the same deterministic code as the Reports page and
the Stage 8 suggester; no model is involved. Suggestions are stored, so the user can decide
later and the page shows what was accepted or rejected. Accepting goes through
``accept_suggestion``, which re-checks everything before ``apply_settings`` saves it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from glucobalance.adjustment_service import (
    REVIEW_PERIOD_DAYS,
    SuggestionError,
    accept_suggestion,
    suggestions_for,
)
from glucobalance.adjustments import Setting, Suggestion
from glucobalance.analytics_service import Analytics, build_analytics
from glucobalance.models import StoredSuggestion, SuggestionStatus, User
from glucobalance.patterns import PatternKind

MAX_SUGGESTIONS = 3


@dataclass(frozen=True, slots=True)
class Review:
    analytics: Analytics
    suggestions: list[StoredSuggestion]


def to_suggestion(row: StoredSuggestion) -> Suggestion:
    return Suggestion(
        pattern=PatternKind(row.pattern),
        block_start=row.block_start,
        setting=Setting(row.setting),
        current=_stored_value(row.current_value, Setting(row.setting)),
        proposed=_stored_value(row.proposed_value, Setting(row.setting)),
        reason=row.reason,
    )


def _stored_value(value: Decimal, setting: Setting) -> Decimal:
    """ICR keeps one decimal; ISF is a whole number (the database keeps one decimal for both)."""
    return value.quantize(Decimal("0.1") if setting is Setting.ICR else Decimal(1))


def pending(session: Session, user: User) -> list[StoredSuggestion]:
    return list(
        session.scalars(
            select(StoredSuggestion)
            .where(
                StoredSuggestion.user_id == user.id,
                StoredSuggestion.status == SuggestionStatus.PENDING,
            )
            .order_by(StoredSuggestion.id)
        )
    )


def recent_decisions(session: Session, user: User, limit: int = 10) -> list[StoredSuggestion]:
    return list(
        session.scalars(
            select(StoredSuggestion)
            .where(
                StoredSuggestion.user_id == user.id,
                StoredSuggestion.status != SuggestionStatus.PENDING,
            )
            .order_by(StoredSuggestion.resolved_at.desc())
            .limit(limit)
        )
    )


def save_suggestions(
    session: Session, user: User, suggestions: Sequence[Suggestion], *, now: datetime
) -> list[StoredSuggestion]:
    """Store ``suggestions`` as pending, at most ``MAX_SUGGESTIONS``. An identical pending one
    is reused; a different pending one for the same block and setting is replaced, because it
    is out of date. Never commits."""
    rows: list[StoredSuggestion] = []
    existing = {(row.block_start, row.setting): row for row in pending(session, user)}
    for suggestion in list(suggestions)[:MAX_SUGGESTIONS]:
        old = existing.get((suggestion.block_start, suggestion.setting.value))
        if old is not None and to_suggestion(old) == suggestion:
            rows.append(old)
            continue
        if old is not None:
            session.delete(old)
        row = StoredSuggestion(
            user_id=user.id,
            created_at=now,
            pattern=suggestion.pattern.value,
            block_start=suggestion.block_start,
            setting=suggestion.setting.value,
            current_value=suggestion.current,
            proposed_value=suggestion.proposed,
            reason=suggestion.reason,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return rows


def run_review(session: Session, user: User, *, now: datetime) -> Review:
    """Summarise the last ``REVIEW_PERIOD_DAYS`` days and store up to three suggestions.
    Pending suggestions the data no longer supports are dropped. Never commits."""
    analytics = build_analytics(session, user, days=REVIEW_PERIOD_DAYS, now=now)
    rows = save_suggestions(session, user, suggestions_for(session, user, now=now), now=now)
    keep = {row.id for row in rows}
    for row in pending(session, user):
        if row.id not in keep:
            session.delete(row)
    session.flush()
    return Review(analytics=analytics, suggestions=rows)


def _own_pending(session: Session, user: User, suggestion_id: int) -> StoredSuggestion:
    row = session.get(StoredSuggestion, suggestion_id)
    if row is None or row.user_id != user.id:
        raise SuggestionError("That suggestion does not exist.")
    if row.status is not SuggestionStatus.PENDING:
        raise SuggestionError("That suggestion has already been decided.")
    return row


def accept(session: Session, user: User, suggestion_id: int, *, now: datetime) -> StoredSuggestion:
    """Apply a pending suggestion (all the Stage 8 checks run again). Never commits."""
    row = _own_pending(session, user, suggestion_id)
    accept_suggestion(session, user, to_suggestion(row), now=now)
    row.status = SuggestionStatus.ACCEPTED
    row.resolved_at = now
    session.flush()
    return row


def reject(session: Session, user: User, suggestion_id: int, *, now: datetime) -> StoredSuggestion:
    row = _own_pending(session, user, suggestion_id)
    row.status = SuggestionStatus.REJECTED
    row.resolved_at = now
    session.flush()
    return row
