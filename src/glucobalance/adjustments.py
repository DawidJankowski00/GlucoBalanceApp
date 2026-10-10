"""The adjustment suggester: turns detected patterns into small, capped setting changes.

A pure function of the findings, the current time blocks and the recent changes. It only
proposes; nothing changes until the user accepts a suggestion (``adjustment_service``), and
every accepted change goes through ``apply_settings`` and the change log.

Rules (each has a test in ``tests/test_adjustments.py``):

1. Night lows: raise the ISF of the block in force at 03:00 (smaller corrections overnight).
2. High fasting values: lower the ISF of that same block (bigger corrections overnight).
3. Highs after breakfast: lower the ICR of the block in force at breakfast (more insulin
   per gram).
4. Safety first: a block with a low pattern never gets a change that means more insulin, so
   rule 1 wins over rules 2 and 3 when they meet in one block.
5. A change is at most ``MAX_CHANGE`` of the current value, rounded towards no change (ICR to
   0.1 g, ISF to 1 mg/dL), and stays inside the limits the settings page accepts. A change
   that rounds to nothing is not suggested.
6. One change per setting per review period: a block's ICR or ISF that changed in the last
   ``REVIEW_DAYS`` days, by anyone, gets no suggestion.
7. At most one suggestion per block and setting.
"""

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from glucobalance.dosing_safety import block_at
from glucobalance.patterns import AFTER_MEAL_FROM, AFTER_MEAL_TO, Finding, PatternKind
from glucobalance.settings_service import TimeBlockInput

MAX_CHANGE = Decimal("0.10")
REVIEW_DAYS = 7
OVERNIGHT = time(3, 0)
# The settings page limits (settings_service._validate_blocks).
ICR_LIMITS = (Decimal(1), Decimal(150))
ISF_LIMITS = (Decimal(5), Decimal(400))


class Setting(StrEnum):
    ICR = "icr"
    ISF = "isf"


@dataclass(frozen=True, slots=True)
class RecentChange:
    """A block's ICR or ISF changed at ``changed_at``."""

    block_start: time
    setting: Setting
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Change ``setting`` of the block starting at ``block_start`` from ``current`` to
    ``proposed``, because of ``pattern``. ``reason`` is safe to show to the user."""

    pattern: PatternKind
    block_start: time
    setting: Setting
    current: Decimal
    proposed: Decimal
    reason: str

    @property
    def more_insulin(self) -> bool:
        """A lower ICR or ISF means more insulin for the same carbs or glucose."""
        return self.proposed < self.current


def frozen_settings(changes: Iterable[RecentChange], now: datetime) -> set[tuple[time, Setting]]:
    """The block settings that changed in the last ``REVIEW_DAYS`` days (rule 6)."""
    since = now - timedelta(days=REVIEW_DAYS)
    return {(c.block_start, c.setting) for c in changes if c.changed_at > since}


def capped_value(current: Decimal, setting: Setting, *, up: bool) -> Decimal:
    """``current`` moved by at most ``MAX_CHANGE`` in one direction, rounded towards it."""
    quantum = Decimal("0.1") if setting is Setting.ICR else Decimal(1)
    low, high = ICR_LIMITS if setting is Setting.ICR else ISF_LIMITS
    delta = (current * MAX_CHANGE).quantize(quantum, rounding=ROUND_DOWN)
    proposed = current + delta if up else current - delta
    return min(max(proposed, low), high)


def _breakfast_time(finding: Finding, zone: ZoneInfo) -> time:
    """The typical breakfast time: the median peak time less the middle of the meal window."""
    back = (AFTER_MEAL_FROM + AFTER_MEAL_TO) / 2
    minutes = [
        (e.measured_at - back).astimezone(zone).hour * 60
        + (e.measured_at - back).astimezone(zone).minute
        for e in finding.evidence
    ]
    middle = int(statistics.median(minutes))
    return time(middle // 60, middle % 60)


def _value(block: TimeBlockInput, setting: Setting) -> Decimal:
    return block.icr_grams_per_unit if setting is Setting.ICR else Decimal(block.isf_mgdl)


_REASONS = {
    PatternKind.NIGHT_LOWS: "Repeated night lows: a higher sensitivity factor makes overnight "
    "corrections smaller. Night lows can also come from basal insulin; talk to your clinic.",
    PatternKind.HIGH_FASTING: "High fasting values: a lower sensitivity factor makes overnight "
    "corrections bigger. Fasting highs often come from basal insulin; talk to your clinic.",
    PatternKind.POST_BREAKFAST_HIGHS: "Highs after breakfast: a lower carb ratio gives a little "
    "more insulin for the same breakfast.",
}


def suggest_adjustments(
    findings: Sequence[Finding],
    blocks: Sequence[TimeBlockInput],
    recent_changes: Iterable[RecentChange],
    *,
    now: datetime,
    zone: ZoneInfo,
) -> list[Suggestion]:
    """The capped suggestions for ``findings``, in the order of the findings."""
    block_list = list(blocks)
    frozen = frozen_settings(recent_changes, now)

    candidates: list[tuple[PatternKind, TimeBlockInput, Setting, bool]] = []
    low_blocks: set[time] = set()
    for finding in findings:
        if finding.kind is PatternKind.NIGHT_LOWS:
            block = block_at(block_list, OVERNIGHT)
            if block is not None:
                low_blocks.add(block.start_time)
                candidates.append((finding.kind, block, Setting.ISF, True))
        elif finding.kind is PatternKind.HIGH_FASTING:
            block = block_at(block_list, OVERNIGHT)
            if block is not None:
                candidates.append((finding.kind, block, Setting.ISF, False))
        elif finding.kind is PatternKind.POST_BREAKFAST_HIGHS and finding.evidence:
            block = block_at(block_list, _breakfast_time(finding, zone))
            if block is not None:
                candidates.append((finding.kind, block, Setting.ICR, False))

    suggestions: list[Suggestion] = []
    taken: set[tuple[time, Setting]] = set()
    for kind, block, setting, up in candidates:
        key = (block.start_time, setting)
        if key in frozen or key in taken:
            continue
        if not up and block.start_time in low_blocks:
            continue  # rule 4: never more insulin in a block with lows
        current = _value(block, setting)
        proposed = capped_value(current, setting, up=up)
        if proposed == current:
            continue
        taken.add(key)
        suggestions.append(
            Suggestion(kind, block.start_time, setting, current, proposed, _REASONS[kind])
        )
    return suggestions
