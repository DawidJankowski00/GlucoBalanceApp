"""Suggestions from the last two weeks of data, and accepting one.

Accepting re-checks everything (the value is unchanged, the setting is not frozen, the change
is within the cap) and saves through ``apply_settings`` with ``ASSISTANT_SUGGESTION`` as the
source, so the change log shows where every suggested change came from.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.adjustments import (
    REVIEW_DAYS,
    RecentChange,
    Setting,
    Suggestion,
    capped_value,
    frozen_settings,
    suggest_adjustments,
)
from glucobalance.analytics_service import build_analytics
from glucobalance.models import ChangeSource, SettingsChange, User
from glucobalance.settings_service import TimeBlockInput, apply_settings, history, to_input

REVIEW_PERIOD_DAYS = 14  # how much data a review looks at

_BLOCK = re.compile(r"(\d{2}):(\d{2}) icr=(\S+) isf=(\d+)")


class SuggestionError(ValueError):
    """The suggestion can no longer be applied. The message is safe to show to the user."""


def _parse_blocks(text: str | None) -> dict[time, tuple[str, str]]:
    if not text:
        return {}
    return {time(int(h), int(m)): (icr, isf) for h, m, icr, isf in _BLOCK.findall(text)}


def recent_changes(changes: Sequence[SettingsChange]) -> list[RecentChange]:
    """Each block ICR or ISF that a ``time_blocks`` change touched, with when it changed.

    The log stores the whole block list as text, so the two versions are compared block by
    block. A new block counts as a change to both of its settings.
    """
    found: list[RecentChange] = []
    for change in changes:
        if change.field != "time_blocks":
            continue
        old = _parse_blocks(change.old_value)
        for start, (icr, isf) in _parse_blocks(change.new_value).items():
            before = old.get(start)
            if before is None or before[0] != icr:
                found.append(RecentChange(start, Setting.ICR, change.changed_at))
            if before is None or before[1] != isf:
                found.append(RecentChange(start, Setting.ISF, change.changed_at))
    return found


def suggestions_for(session: Session, user: User, *, now: datetime) -> list[Suggestion]:
    """Capped suggestions from the patterns in the last ``REVIEW_PERIOD_DAYS`` days."""
    settings = user.settings
    if settings is None:
        return []
    findings = build_analytics(session, user, days=REVIEW_PERIOD_DAYS, now=now).findings
    return suggest_adjustments(
        findings,
        to_input(settings).time_blocks,
        recent_changes(history(session, user)),
        now=now,
        zone=ZoneInfo(settings.timezone),
    )


def accept_suggestion(
    session: Session, user: User, suggestion: Suggestion, *, now: datetime
) -> None:
    """Apply ``suggestion`` after checking it still holds. Never commits."""
    settings = user.settings
    if settings is None:
        raise SuggestionError("Set up your treatment settings first.")
    data = to_input(settings)
    block = next((b for b in data.time_blocks if b.start_time == suggestion.block_start), None)
    if block is None:
        raise SuggestionError("That time block no longer exists.")
    current = block.icr_grams_per_unit if suggestion.setting is Setting.ICR else block.isf_mgdl
    if current != suggestion.current:
        raise SuggestionError("That setting has changed since the suggestion was made.")
    if capped_value(suggestion.current, suggestion.setting, up=suggestion.proposed > current) != (
        suggestion.proposed
    ):
        raise SuggestionError("That change is bigger than the app allows.")
    frozen = frozen_settings(recent_changes(history(session, user)), now)
    if (suggestion.block_start, suggestion.setting) in frozen:
        raise SuggestionError(f"That setting already changed in the last {REVIEW_DAYS} days.")

    if suggestion.setting is Setting.ICR:
        new_block = replace(block, icr_grams_per_unit=suggestion.proposed)
    else:
        new_block = replace(block, isf_mgdl=int(suggestion.proposed))
    blocks: tuple[TimeBlockInput, ...] = tuple(
        new_block if b.start_time == block.start_time else b for b in data.time_blocks
    )
    apply_settings(
        session, user, replace(data, time_blocks=blocks), ChangeSource.ASSISTANT_SUGGESTION, user
    )
