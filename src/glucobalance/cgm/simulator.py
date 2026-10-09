"""A pretend CGM for demos, tests and CI: it never talks to a real server.

The simulator replays a one-day glucose trace (one value every 5 minutes) against the real
clock. Each 5-minute slot since 1970 maps to one value of the trace, so the same moment
always gives the same reading and running the import twice stores nothing new.

The trace comes from simglucose (the UVA/Padova simulator) when the optional ``sim`` group is
installed, and from ``demo_trace`` otherwise. Tests pass their own short trace.
"""

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from glucobalance.cgm.base import CGMReading, trend_from_rate

STEP = timedelta(minutes=5)
# Never replay more than this much history, however old ``since`` is.
MAX_HISTORY = timedelta(hours=24)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


class SimulatorSource:
    """A ``CGMSource`` that replays ``trace`` in 5-minute steps, repeating it forever."""

    def __init__(self, trace: Sequence[int], *, clock: Callable[[], datetime] = _now) -> None:
        if not trace:
            raise ValueError("the simulator needs a trace with at least one value")
        self._trace = list(trace)
        self._clock = clock

    def _value(self, slot: int) -> int:
        return self._trace[slot % len(self._trace)]

    def fetch_readings(self, since: datetime) -> list[CGMReading]:
        now = self._clock()
        since = max(since, now - MAX_HISTORY)
        first = (since - _EPOCH) // STEP + 1  # the first slot strictly after ``since``
        last = (now - _EPOCH) // STEP
        minutes = STEP.total_seconds() / 60
        readings = []
        for slot in range(first, last + 1):
            value = self._value(slot)
            readings.append(
                CGMReading(
                    measured_at=_EPOCH + slot * STEP,
                    value_mgdl=value,
                    trend=trend_from_rate((value - self._value(slot - 1)) / minutes),
                )
            )
        return readings


def _bump(minute: float, centre: float, height: float, width: float) -> float:
    return height * math.exp(-(((minute - centre) / width) ** 2))


def demo_trace() -> list[int]:
    """A plausible day without simglucose: meals, a dawn rise and one afternoon low."""
    values = []
    for slot in range(24 * 60 // 5):
        minute = slot * 5.0
        glucose = (
            125
            + 8 * math.sin(minute / 47)  # small wobble so the line is not flat
            + _bump(minute, 6 * 60, 20, 60)  # dawn phenomenon
            + _bump(minute, 8 * 60 + 30, 95, 45)  # breakfast
            + _bump(minute, 13 * 60 + 30, 70, 50)  # lunch
            - _bump(minute, 16 * 60, 72, 25)  # an afternoon low, so alerts can be seen
            + _bump(minute, 19 * 60 + 30, 85, 55)  # dinner
        )
        values.append(round(glucose))
    return values


def default_trace() -> list[int]:  # pragma: no cover - depends on the optional sim group
    """One simulated day from simglucose if it is installed, else ``demo_trace``."""
    try:
        from glucobalance.seed import simulate

        start = datetime(2026, 1, 1, tzinfo=UTC)
        readings = simulate(days=1, start=start).readings
    except ImportError:
        return demo_trace()
    # simglucose samples every 3 minutes; keep the value closest to each 5-minute slot.
    by_minute = {round((at - start).total_seconds() / 60): v for at, v in readings}
    return [
        by_minute[min(by_minute, key=lambda m: abs(m - slot * 5))] for slot in range(24 * 60 // 5)
    ]
