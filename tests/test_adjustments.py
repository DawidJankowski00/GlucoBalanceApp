"""The adjustment suggester: patterns in, capped suggestions out."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from glucobalance.adjustments import (
    REVIEW_DAYS,
    RecentChange,
    Setting,
    Suggestion,
    capped_value,
    suggest_adjustments,
)
from glucobalance.patterns import Evidence, Finding, PatternKind
from glucobalance.settings_service import TimeBlockInput

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
UTC_ZONE = ZoneInfo("UTC")
D = Decimal

BLOCKS = (
    TimeBlockInput(time(0, 0), D("12"), 50),  # overnight
    TimeBlockInput(time(6, 0), D("10"), 40),  # breakfast
    TimeBlockInput(time(11, 0), D("15"), 60),
)


def finding(kind: PatternKind, *peaks: datetime) -> Finding:
    return Finding(kind, "t", "d", 100.0, tuple(Evidence(p, 100) for p in peaks))


NIGHT_LOWS = finding(PatternKind.NIGHT_LOWS)
HIGH_FASTING = finding(PatternKind.HIGH_FASTING)
# Peaks around 09:30 mean breakfast around 07:30, in the 06:00 block.
BREAKFAST = finding(
    PatternKind.POST_BREAKFAST_HIGHS,
    *(datetime(2026, 10, d, 9, 30, tzinfo=UTC) for d in (5, 6, 7)),
)


def suggest(
    *findings: Finding,
    blocks: tuple[TimeBlockInput, ...] = BLOCKS,
    changes: tuple[RecentChange, ...] = (),
) -> list[Suggestion]:
    return suggest_adjustments(findings, blocks, changes, now=NOW, zone=UTC_ZONE)


def only(suggestions: list[Suggestion]) -> Suggestion:
    assert len(suggestions) == 1
    return suggestions[0]


def test_no_findings_no_suggestions() -> None:
    assert suggest() == []


def test_night_lows_raise_the_overnight_isf_by_ten_percent() -> None:
    s = only(suggest(NIGHT_LOWS))
    assert (s.block_start, s.setting, s.current, s.proposed) == (time(0), Setting.ISF, D(50), D(55))
    assert not s.more_insulin


def test_high_fasting_lowers_the_overnight_isf() -> None:
    s = only(suggest(HIGH_FASTING))
    assert (s.block_start, s.setting, s.proposed) == (time(0), Setting.ISF, D(45))
    assert s.more_insulin


def test_breakfast_highs_lower_the_icr_of_the_breakfast_block() -> None:
    s = only(suggest(BREAKFAST))
    assert (s.block_start, s.setting, s.current, s.proposed) == (
        time(6),
        Setting.ICR,
        D("10"),
        D("9.0"),
    )


def test_the_breakfast_block_follows_the_local_clock() -> None:
    # In Tokyo (UTC+9) a 09:30 UTC peak is 18:30 local, so breakfast was about 16:30.
    s = only(suggest_adjustments([BREAKFAST], BLOCKS, [], now=NOW, zone=ZoneInfo("Asia/Tokyo")))
    assert s.block_start == time(11)


def test_lows_win_over_fasting_highs_in_the_same_block() -> None:
    s = only(suggest(HIGH_FASTING, NIGHT_LOWS))
    assert s.pattern is PatternKind.NIGHT_LOWS


def test_no_more_insulin_in_a_block_with_lows() -> None:
    one_block = (TimeBlockInput(time(0, 0), D("10"), 50),)
    s = only(suggest(NIGHT_LOWS, BREAKFAST, blocks=one_block))
    assert s.pattern is PatternKind.NIGHT_LOWS


def test_separate_blocks_each_get_a_suggestion() -> None:
    kinds = [s.pattern for s in suggest(NIGHT_LOWS, BREAKFAST)]
    assert kinds == [PatternKind.NIGHT_LOWS, PatternKind.POST_BREAKFAST_HIGHS]


def test_a_setting_changed_in_the_review_period_is_left_alone() -> None:
    recent = RecentChange(time(0), Setting.ISF, NOW - timedelta(days=REVIEW_DAYS - 1))
    assert suggest(NIGHT_LOWS, changes=(recent,)) == []


def test_a_change_before_the_review_period_does_not_block() -> None:
    old = RecentChange(time(0), Setting.ISF, NOW - timedelta(days=REVIEW_DAYS + 1))
    assert len(suggest(NIGHT_LOWS, changes=(old,))) == 1


def test_a_recent_change_to_the_other_setting_does_not_block() -> None:
    recent = RecentChange(time(0), Setting.ICR, NOW - timedelta(days=1))
    assert len(suggest(NIGHT_LOWS, changes=(recent,))) == 1


def test_the_change_rounds_towards_no_change() -> None:
    assert capped_value(D("13"), Setting.ICR, up=False) == D("11.7")
    assert capped_value(D("7.5"), Setting.ICR, up=False) == D("6.8")  # 0.75 rounds to 0.7
    assert capped_value(D("47"), Setting.ISF, up=True) == D("51")  # 4.7 rounds to 4


def test_a_change_that_rounds_to_nothing_is_not_suggested() -> None:
    tiny = (TimeBlockInput(time(0, 0), D("10"), 9),)  # 10% of 9 is 0.9, which rounds to 0
    assert suggest(NIGHT_LOWS, blocks=tiny) == []


def test_values_stay_inside_the_settings_limits() -> None:
    assert capped_value(D("400"), Setting.ISF, up=True) == D("400")
    assert capped_value(D("150"), Setting.ICR, up=True) == D("150")


def test_every_suggestion_has_a_reason() -> None:
    assert all(s.reason for s in suggest(NIGHT_LOWS, BREAKFAST))
