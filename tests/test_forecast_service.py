"""The "likely low soon" warning: when it shows, and every reason it stays hidden."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from glucobalance.cgm_service import use_simulator
from glucobalance.forecast.features import FEATURE_NAMES
from glucobalance.forecast.models import LinearTrend
from glucobalance.forecast_service import load_history, low_soon
from glucobalance.models import (
    CarbEntry,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    ReadingSource,
)
from test_cgm_service import make_user

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)


def add_readings(
    session: Session, user_id: int, values: Sequence[int], *, last: datetime = NOW
) -> None:
    """``values`` oldest first, one every 5 minutes, ending at ``last``."""
    for i, value in enumerate(reversed(values)):
        session.add(
            GlucoseReading(
                user_id=user_id,
                measured_at=last - timedelta(minutes=5 * i),
                value_mgdl=value,
                source=ReadingSource.SIMULATED,
            )
        )
    session.flush()


FALLING = [140, 132, 124, 116, 108, 100, 92]  # 1.6 mg/dL a minute: 44 in 30 minutes
STEADY = [120] * 7


def test_a_steady_fall_towards_a_low_shows_the_warning(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, FALLING)
    warning = low_soon(session, user, LinearTrend(), now=NOW + timedelta(minutes=2))
    assert warning is not None
    assert warning.within_minutes == 30
    assert warning.model == "linear trend"
    assert warning.predicted_mgdl == 44


def test_no_warning_when_steady(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, STEADY)
    assert low_soon(session, user, LinearTrend(), now=NOW) is None


def test_no_warning_from_stale_data(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, FALLING)
    assert low_soon(session, user, LinearTrend(), now=NOW + timedelta(minutes=16)) is None


def test_no_warning_with_gaps(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, FALLING[-3:])  # only 10 minutes of history
    assert low_soon(session, user, LinearTrend(), now=NOW) is None


def test_no_warning_without_a_cgm(session: Session) -> None:
    meter = make_user(session, MonitoringMode.GLUCOMETER)
    add_readings(session, meter.id, FALLING)
    assert low_soon(session, meter, LinearTrend(), now=NOW) is None


def test_no_warning_without_a_connection(session: Session) -> None:
    user = make_user(session)
    add_readings(session, user.id, FALLING)
    assert load_history(session, user, now=NOW) is None
    assert low_soon(session, user, LinearTrend(), now=NOW) is None


def test_history_holds_cgm_readings_rapid_boluses_and_carbs(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, STEADY)
    session.add_all(
        [
            GlucoseReading(
                user_id=user.id,
                measured_at=NOW - timedelta(minutes=1),
                value_mgdl=99,
                source=ReadingSource.MANUAL,  # a finger-prick: not part of the CGM line
            ),
            InsulinDose(
                user_id=user.id,
                taken_at=NOW - timedelta(hours=1),
                units=Decimal("3"),
                insulin_type=InsulinType.RAPID,
                kind=DoseKind.BOLUS,
            ),
            InsulinDose(
                user_id=user.id,
                taken_at=NOW - timedelta(hours=2),
                units=Decimal("14"),
                insulin_type=InsulinType.LONG,
                kind=DoseKind.BASAL,
            ),
            CarbEntry(user_id=user.id, eaten_at=NOW - timedelta(minutes=40), grams=Decimal(45)),
            CarbEntry(user_id=user.id, eaten_at=NOW - timedelta(hours=5), grams=Decimal(30)),
        ]
    )
    session.flush()
    history = load_history(session, user, now=NOW)
    assert history is not None
    assert [v for _, v in history.readings] == STEADY
    assert [u for _, u in history.boluses] == [3.0]
    assert [g for _, g in history.carbs] == [45.0]


class Recorder:
    """A forecaster that remembers the rows it was given and predicts a low."""

    name = "recorder"

    def __init__(self) -> None:
        self.rows: list[Sequence[float]] = []

    def predict(self, rows: Sequence[Sequence[float]]) -> list[float]:
        self.rows += rows
        return [60.0 for _ in rows]


def test_the_forecaster_gets_one_row_for_the_newest_reading(session: Session) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)
    add_readings(session, user.id, STEADY)
    recorder = Recorder()
    assert low_soon(session, user, recorder, now=NOW) is not None
    assert len(recorder.rows) == 1
    assert len(recorder.rows[0]) == len(FEATURE_NAMES)
