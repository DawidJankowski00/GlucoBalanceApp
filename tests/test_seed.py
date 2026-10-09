from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from glucobalance.models import (
    DeliveryMode,
    GlucoseReading,
    InsulinDose,
    MonitoringMode,
    ReadingSource,
    Reminder,
    SitePurpose,
    SiteUse,
    Trend,
)
from glucobalance.seed import (
    DEMO_EMAIL,
    SimulatedData,
    ensure_body_sites,
    seed_demo_user,
    trend_from_change,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


def fake_data(days: int = 7) -> SimulatedData:
    """Flat 120 mg/dL with a rise after breakfast, one meal and bolus a day."""
    readings = []
    for step in range(days * 24 * 12):
        at = START + timedelta(minutes=5 * step)
        value = 160 if at.hour == 9 else 120
        readings.append((at, value))
    meals = [(START + timedelta(days=d, hours=8), Decimal("50")) for d in range(days)]
    boluses = [(START + timedelta(days=d, hours=8), Decimal("4.6713")) for d in range(days)]
    return SimulatedData(readings=readings, meals=meals, boluses=boluses)


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (120, 120, Trend.STEADY),
        (120, 125, Trend.STEADY),
        (120, 130, Trend.RISING),
        (120, 135, Trend.RISING_FAST),
        (120, 110, Trend.FALLING),
        (120, 100, Trend.FALLING_FAST),
    ],
)
def test_trend_from_change_over_five_minutes(previous: int, current: int, expected: Trend) -> None:
    assert trend_from_change(previous, current, minutes=5) is expected


def test_ensure_body_sites_is_idempotent(session: Session) -> None:
    first = ensure_body_sites(session)
    second = ensure_body_sites(session)
    assert len(first) > 0
    assert [s.id for s in first] == [s.id for s in second]


def test_seed_creates_a_pump_and_cgm_demo_user(session: Session) -> None:
    user = seed_demo_user(session, fake_data())
    assert user.email == DEMO_EMAIL
    assert user.settings is not None
    assert user.settings.delivery_mode is DeliveryMode.PUMP
    assert user.settings.monitoring_mode is MonitoringMode.CGM
    assert len(user.settings.time_blocks) >= 2


def test_seed_stores_every_reading_as_simulated_with_a_trend(session: Session) -> None:
    seed_demo_user(session, fake_data())
    readings = session.scalars(select(GlucoseReading).order_by(GlucoseReading.measured_at)).all()
    assert len(readings) == 7 * 24 * 12
    assert {r.source for r in readings} == {ReadingSource.SIMULATED}
    assert readings[0].trend is None  # nothing to compare the first reading with
    assert all(r.trend is not None for r in readings[1:])


def test_seed_rounds_boluses_to_the_pump_step_and_links_the_infusion_set(
    session: Session,
) -> None:
    seed_demo_user(session, fake_data())
    doses = session.scalars(select(InsulinDose)).all()
    assert len(doses) == 7
    assert {d.units for d in doses} == {Decimal("4.65")}
    assert all(
        d.site_use is not None and d.site_use.purpose is SitePurpose.INFUSION_SET for d in doses
    )


def test_seed_changes_the_infusion_set_every_three_days(session: Session) -> None:
    seed_demo_user(session, fake_data())
    sets = session.scalars(
        select(SiteUse).where(SiteUse.purpose == SitePurpose.INFUSION_SET).order_by(SiteUse.used_at)
    ).all()
    assert [s.used_at for s in sets] == [START + timedelta(days=d) for d in (0, 3, 6)]
    assert len({s.site_id for s in sets}) == 3  # a different site each time
    assert session.scalars(select(Reminder)).all() != []


def test_seed_refuses_to_overwrite_unless_asked(session: Session) -> None:
    seed_demo_user(session, fake_data(days=1))
    with pytest.raises(ValueError, match="already exists"):
        seed_demo_user(session, fake_data(days=1))

    seed_demo_user(session, fake_data(days=2), replace=True)
    assert len(session.scalars(select(GlucoseReading)).all()) == 2 * 24 * 12


def test_from_results_converts_simglucose_rates_to_amounts() -> None:
    pd = pytest.importorskip("pandas")
    from glucobalance.seed import from_results

    index = pd.date_range("2026-09-01 08:00", periods=3, freq="5min", name="Time")
    frame = pd.DataFrame(
        {"CGM": [120.4, 130.6, 140.0], "CHO": [0.0, 10.0, 0.0], "insulin": [0.01, 1.01, 0.01]},
        index=index,
    )
    data = from_results(frame, basal_u_per_min=0.01, sample_minutes=5)
    assert data.readings[0] == (datetime(2026, 9, 1, 8, 0, tzinfo=UTC), 120)
    assert data.readings[1][1] == 131
    assert data.meals == [(datetime(2026, 9, 1, 8, 5, tzinfo=UTC), Decimal("50.0"))]
    assert data.boluses == [(datetime(2026, 9, 1, 8, 5, tzinfo=UTC), Decimal("5.00"))]
