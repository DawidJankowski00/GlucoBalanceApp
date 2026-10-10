"""Rule-based pattern detectors: night lows, post-breakfast highs and high fasting values."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from glucobalance.models import CarbEntry, GlucoseReading, GlucoseTag, ReadingSource
from glucobalance.patterns import (
    PatternKind,
    detect_patterns,
    high_fasting,
    night_lows,
    post_breakfast_highs,
)

WARSAW = ZoneInfo("Europe/Warsaw")  # UTC+2 in October 2026


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A local Warsaw time on October ``day`` 2026, as UTC."""
    return datetime(2026, 10, day, hour, minute, tzinfo=WARSAW).astimezone(UTC)


def reading(
    day: int, hour: int, value: int, minute: int = 0, tag: GlucoseTag | None = None
) -> GlucoseReading:
    return GlucoseReading(
        user_id=1,
        measured_at=at(day, hour, minute),
        value_mgdl=value,
        source=ReadingSource.CGM,
        tag=tag,
    )


def breakfast(day: int, hour: int = 8, minute: int = 0) -> CarbEntry:
    return CarbEntry(user_id=1, eaten_at=at(day, hour, minute), grams=Decimal("45"))


# ---- night lows ----


def test_three_nights_with_lows_make_a_finding() -> None:
    readings = [reading(day, 3, 62) for day in (1, 2, 3)] + [reading(4, 3, 110)]
    finding = night_lows(readings, WARSAW)
    assert finding is not None
    assert finding.kind is PatternKind.NIGHT_LOWS
    assert "3 nights" in finding.detail
    assert len(finding.evidence) == 3
    assert finding.headline_mgdl == 62


def test_two_nights_are_not_a_pattern() -> None:
    assert night_lows([reading(1, 3, 60), reading(2, 4, 60)], WARSAW) is None


def test_many_lows_in_one_night_count_once() -> None:
    readings = [reading(1, 1, 60), reading(1, 2, 58), reading(1, 3, 55), reading(2, 3, 60)]
    assert night_lows(readings, WARSAW) is None


def test_the_lowest_reading_of_each_night_is_the_evidence() -> None:
    readings = [reading(d, 2, 65) for d in (1, 2, 3)] + [reading(1, 4, 55)]
    finding = night_lows(readings, WARSAW)
    assert finding is not None
    assert finding.headline_mgdl == 55
    assert sorted(e.value_mgdl for e in finding.evidence) == [55, 65, 65]


def test_lows_outside_the_night_are_ignored() -> None:
    assert night_lows([reading(d, 14, 60) for d in (1, 2, 3, 4)], WARSAW) is None


def test_night_is_judged_in_local_time() -> None:
    # 23:30 UTC on 1 Oct is 01:30 local, so night; 03:00 UTC is 05:00 local, also night
    readings = [
        GlucoseReading(
            user_id=1,
            measured_at=datetime(2026, 10, d, 23, 30, tzinfo=UTC),
            value_mgdl=60,
            source=ReadingSource.CGM,
        )
        for d in (1, 2, 3)
    ]
    assert night_lows(readings, WARSAW) is not None


# ---- post-breakfast highs ----


def high_mornings(days: tuple[int, ...], peak: int = 240) -> list[GlucoseReading]:
    return [reading(day, 10, peak) for day in days]  # two hours after an 08:00 breakfast


def test_repeated_highs_after_breakfast_make_a_finding() -> None:
    days = (1, 2, 3, 4, 5)
    finding = post_breakfast_highs(
        high_mornings(days), [breakfast(d) for d in days], WARSAW, high=180
    )
    assert finding is not None
    assert finding.kind is PatternKind.POST_BREAKFAST_HIGHS
    assert "5 of 5" in finding.detail
    assert finding.headline_mgdl == 240


def test_the_first_hour_after_eating_is_ignored() -> None:
    days = (1, 2, 3, 4, 5)
    early = [reading(d, 8, 240, minute=30) for d in days]  # 30 min after breakfast
    assert post_breakfast_highs(early, [breakfast(d) for d in days], WARSAW, high=180) is None


def test_in_range_mornings_are_not_a_pattern() -> None:
    days = (1, 2, 3, 4, 5)
    assert (
        post_breakfast_highs(
            high_mornings(days, peak=150), [breakfast(d) for d in days], WARSAW, high=180
        )
        is None
    )


def test_too_few_breakfast_days_are_not_a_pattern() -> None:
    days = (1, 2, 3)
    assert (
        post_breakfast_highs(high_mornings(days), [breakfast(d) for d in days], WARSAW, high=180)
        is None
    )


def test_a_minority_of_high_days_is_not_a_pattern() -> None:
    days = (1, 2, 3, 4, 5, 6, 7)
    readings = high_mornings((1, 2, 3)) + [reading(d, 10, 140) for d in (4, 5, 6, 7)]
    assert post_breakfast_highs(readings, [breakfast(d) for d in days], WARSAW, high=180) is None


def test_only_the_first_morning_meal_counts_as_breakfast() -> None:
    days = (1, 2, 3, 4, 5)
    # a snack at 14:00 is not breakfast; with no morning meal there is nothing to judge
    snacks = [breakfast(d, hour=14) for d in days]
    assert post_breakfast_highs(high_mornings(days), snacks, WARSAW, high=180) is None


# ---- high fasting ----


def test_tagged_fasting_values_above_the_goal_make_a_finding() -> None:
    readings = [reading(d, 7, 150, tag=GlucoseTag.FASTING) for d in range(1, 7)]
    finding = high_fasting(readings, WARSAW)
    assert finding is not None
    assert finding.kind is PatternKind.HIGH_FASTING
    assert finding.headline_mgdl == 150
    assert "6 of 6" in finding.detail


def test_untagged_early_morning_values_stand_in_for_fasting() -> None:
    readings = [reading(d, 6, 150) for d in range(1, 7)]
    assert high_fasting(readings, WARSAW) is not None


def test_fasting_values_within_the_goal_are_fine() -> None:
    readings = [reading(d, 7, 110, tag=GlucoseTag.FASTING) for d in range(1, 7)]
    assert high_fasting(readings, WARSAW) is None


def test_too_few_fasting_days_are_not_a_pattern() -> None:
    readings = [reading(d, 7, 160, tag=GlucoseTag.FASTING) for d in range(1, 4)]
    assert high_fasting(readings, WARSAW) is None


def test_only_the_first_fasting_value_of_a_day_counts() -> None:
    readings = [reading(d, 6, 110) for d in range(1, 7)] + [reading(d, 7, 200) for d in range(1, 7)]
    assert high_fasting(readings, WARSAW) is None


# ---- all together ----


def test_detect_patterns_returns_every_finding() -> None:
    readings = [reading(d, 3, 60) for d in (1, 2, 3)] + [
        reading(d, 7, 150, tag=GlucoseTag.FASTING) for d in range(1, 7)
    ]
    kinds = [f.kind for f in detect_patterns(readings, [], WARSAW, high=180)]
    assert kinds == [PatternKind.NIGHT_LOWS, PatternKind.HIGH_FASTING]


def test_detect_patterns_is_empty_without_data() -> None:
    assert detect_patterns([], [], WARSAW, high=180) == []
