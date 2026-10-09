"""Which live alert applies, and when it is sent again."""

from datetime import UTC, datetime, timedelta

import pytest

from glucobalance.cgm.alerts import Latest, classify, is_stale, should_send
from glucobalance.models import GlucoseAlertKind, Trend

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)
LOW, HIGH = 70, 180


def latest(value: int, trend: Trend | None = Trend.STEADY, age_minutes: int = 2) -> Latest:
    return Latest(NOW - timedelta(minutes=age_minutes), value, trend)


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        (latest(110), None),
        (latest(69), GlucoseAlertKind.LOW),
        (latest(181), GlucoseAlertKind.HIGH),
        (latest(130, Trend.FALLING_FAST), GlucoseAlertKind.FALLING_FAST),
        (latest(60, Trend.FALLING_FAST), GlucoseAlertKind.LOW),  # low outranks falling
        (latest(250, Trend.FALLING_FAST), GlucoseAlertKind.FALLING_FAST),
        (latest(60, age_minutes=16), GlucoseAlertKind.STALE),  # an old low is not trusted
        (None, GlucoseAlertKind.STALE),
    ],
)
def test_classify(reading: Latest | None, expected: GlucoseAlertKind | None) -> None:
    assert classify(reading, low_mgdl=LOW, high_mgdl=HIGH, now=NOW) is expected


def test_the_range_limits_are_not_alerts() -> None:
    assert classify(latest(LOW), low_mgdl=LOW, high_mgdl=HIGH, now=NOW) is None
    assert classify(latest(HIGH), low_mgdl=LOW, high_mgdl=HIGH, now=NOW) is None


def test_stale_after_fifteen_minutes() -> None:
    assert not is_stale(NOW - timedelta(minutes=15), NOW)
    assert is_stale(NOW - timedelta(minutes=15, seconds=1), NOW)
    assert is_stale(None, NOW)


def test_a_new_episode_is_sent() -> None:
    assert should_send(
        GlucoseAlertKind.LOW, previous=None, previous_sent_at=None, now=NOW, quiet=False
    )
    assert should_send(
        GlucoseAlertKind.LOW,
        previous=GlucoseAlertKind.HIGH,
        previous_sent_at=NOW - timedelta(minutes=1),
        now=NOW,
        quiet=False,
    )


@pytest.mark.parametrize(
    ("kind", "minutes", "expected"),
    [
        (GlucoseAlertKind.LOW, 14, False),
        (GlucoseAlertKind.LOW, 15, True),
        (GlucoseAlertKind.HIGH, 119, False),
        (GlucoseAlertKind.HIGH, 120, True),
        (GlucoseAlertKind.FALLING_FAST, 30, True),
        (GlucoseAlertKind.STALE, 59, False),
    ],
)
def test_the_same_episode_repeats_only_after_its_interval(
    kind: GlucoseAlertKind, minutes: int, expected: bool
) -> None:
    sent = NOW - timedelta(minutes=minutes)
    assert should_send(kind, previous=kind, previous_sent_at=sent, now=NOW, quiet=False) is expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (GlucoseAlertKind.LOW, True),
        (GlucoseAlertKind.FALLING_FAST, True),
        (GlucoseAlertKind.HIGH, False),
        (GlucoseAlertKind.STALE, False),
    ],
)
def test_quiet_hours_hold_back_only_non_urgent_alerts(
    kind: GlucoseAlertKind, expected: bool
) -> None:
    assert should_send(kind, previous=None, previous_sent_at=None, now=NOW, quiet=True) is expected
