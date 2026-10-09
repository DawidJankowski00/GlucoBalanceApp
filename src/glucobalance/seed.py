"""Seed the database with a simulated demo patient (pump + CGM).

The glucose, meals and insulin come from simglucose, an open-source implementation of the
UVA/Padova Type 1 diabetes simulator. It is an optional dependency group, so run:

    uv run --group sim python -m glucobalance.seed --days 30

Only ``simulate()`` needs simglucose. Everything else is plain Python and is tested with
fake data, so tests and CI never run the simulator.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import cycle
from typing import Any

from sqlalchemy.orm import Session

from glucobalance.config import get_settings
from glucobalance.db import make_engine, make_session_factory
from glucobalance.models import (
    BodySite,
    CarbEntry,
    DeliveryMode,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    ReadingSource,
    Reminder,
    ReminderKind,
    SettingsTimeBlock,
    SitePurpose,
    SiteRegion,
    SiteUse,
    Trend,
    User,
    UserSettings,
)
from glucobalance.repositories import GlucoseRepository, SiteRepository, UserRepository
from glucobalance.sitemap import seed_body_sites

DEMO_EMAIL = "demo-pump-cgm@example.com"
PUMP_STEP = Decimal("0.05")
SET_CHANGE_DAYS = 3
SENSOR_CHANGE_DAYS = 14


@dataclass(frozen=True)
class SimulatedData:
    """Simulator output in app units: (UTC time, mg/dL), (time, grams), (time, units)."""

    readings: list[tuple[datetime, int]]
    meals: list[tuple[datetime, Decimal]]
    boluses: list[tuple[datetime, Decimal]]


def trend_from_change(previous_mgdl: int, current_mgdl: int, minutes: float) -> Trend:
    """Classify the rate of change in mg/dL per minute, like a CGM trend arrow."""
    rate = (current_mgdl - previous_mgdl) / minutes
    if rate < -2:
        return Trend.FALLING_FAST
    if rate < -1:
        return Trend.FALLING
    if rate <= 1:
        return Trend.STEADY
    if rate <= 2:
        return Trend.RISING
    return Trend.RISING_FAST


def from_results(frame: Any, basal_u_per_min: float, sample_minutes: float) -> SimulatedData:
    """Convert a simglucose results DataFrame (rates per minute) into amounts per event.

    ``CHO`` is grams per minute and ``insulin`` units per minute over each sample step.
    Insulin above the basal rate is a bolus.
    """
    readings: list[tuple[datetime, int]] = []
    meals: list[tuple[datetime, Decimal]] = []
    boluses: list[tuple[datetime, Decimal]] = []
    for stamp, row in frame.iterrows():
        at = stamp.to_pydatetime().replace(tzinfo=UTC)
        readings.append((at, round(float(row["CGM"]))))
        grams = float(row["CHO"]) * sample_minutes
        if grams > 0:
            meals.append((at, Decimal(str(grams)).quantize(Decimal("0.1"))))
        bolus = (float(row["insulin"]) - basal_u_per_min) * sample_minutes
        if bolus >= 0.01:
            boluses.append((at, Decimal(str(bolus)).quantize(Decimal("0.01"))))
    return SimulatedData(readings=readings, meals=meals, boluses=boluses)


def simulate(
    days: int, start: datetime, patient: str = "adolescent#001", seed: int = 1
) -> SimulatedData:  # pragma: no cover - needs the optional simglucose group
    """Run simglucose for ``days`` days from ``start`` (UTC) with a basal-bolus controller."""
    from simglucose.actuator.pump import InsulinPump
    from simglucose.controller.basal_bolus_ctrller import BBController
    from simglucose.patient.t1dpatient import T1DPatient
    from simglucose.sensor.cgm import CGMSensor
    from simglucose.simulation.env import T1DSimEnv
    from simglucose.simulation.scenario_gen import RandomScenario
    from simglucose.simulation.sim_engine import SimObj

    naive_start = start.astimezone(UTC).replace(tzinfo=None)  # simglucose uses naive times
    env = T1DSimEnv(
        T1DPatient.withName(patient),
        CGMSensor.withName("GuardianRT", seed=seed),
        InsulinPump.withName("Insulet"),
        RandomScenario(start_time=naive_start, seed=seed),
    )
    run = SimObj(env, BBController(), timedelta(days=days), animate=False, path=None)
    run.simulate()
    frame = run.results()
    basal = float(frame["insulin"].min())
    return from_results(frame, basal_u_per_min=basal, sample_minutes=float(env.sample_time))


# Stage 4 replaces this with the full body map.
def ensure_body_sites(session: Session) -> Sequence[BodySite]:
    """Load the body map if missing; return all sites ordered by code."""
    seed_body_sites(session)
    return SiteRepository(session).all()


def _demo_settings(user: User) -> UserSettings:
    settings = UserSettings(
        user=user,
        delivery_mode=DeliveryMode.PUMP,
        monitoring_mode=MonitoringMode.CGM,
        max_bolus_units=Decimal("15"),
        dose_step_units=PUMP_STEP,
        clinician_contact="Demo diabetes clinic (simulated)",
    )
    settings.time_blocks = [
        SettingsTimeBlock(start_time=start, icr_grams_per_unit=Decimal(icr), isf_mgdl=isf)
        for start, icr, isf in [
            (time(0, 0), "12", 50),
            (time(6, 0), "8", 40),
            (time(11, 0), "10", 45),
            (time(17, 0), "10", 45),
        ]
    ]
    return settings


def seed_demo_user(session: Session, data: SimulatedData, *, replace: bool = False) -> User:
    """Store ``data`` as the demo pump + CGM user. Flushes but does not commit."""
    users = UserRepository(session)
    existing = users.get_by_email(DEMO_EMAIL)
    if existing is not None:
        if not replace:
            raise ValueError(f"demo user {DEMO_EMAIL} already exists (use replace=True)")
        session.delete(existing)
        session.flush()
        session.expunge_all()

    user = users.add(User(email=DEMO_EMAIL, display_name="Demo (pump + CGM)"))
    session.add(_demo_settings(user))

    readings = []
    previous: tuple[datetime, int] | None = None
    for at, value in data.readings:
        trend = None
        if previous is not None:
            minutes = (at - previous[0]).total_seconds() / 60
            trend = trend_from_change(previous[1], value, minutes)
        readings.append(
            GlucoseReading(
                user=user,
                measured_at=at,
                value_mgdl=value,
                source=ReadingSource.SIMULATED,
                trend=trend,
            )
        )
        previous = (at, value)
    GlucoseRepository(session).add_new(readings)

    session.add_all(CarbEntry(user=user, eaten_at=at, grams=g) for at, g in data.meals)

    sites = ensure_body_sites(session)
    set_sites = cycle([s for s in sites if s.region in (SiteRegion.ABDOMEN, SiteRegion.THIGH)])
    sensor_sites = cycle([s for s in sites if s.region is SiteRegion.ARM])
    if data.readings:
        first, last = data.readings[0][0], data.readings[-1][0]
        set_uses = _rotate(
            session, user, set_sites, SitePurpose.INFUSION_SET, first, last, SET_CHANGE_DAYS
        )
        _rotate(
            session, user, sensor_sites, SitePurpose.CGM_SENSOR, first, last, SENSOR_CHANGE_DAYS
        )
        for at, units in data.boluses:
            current_set = max((u for u in set_uses if u.used_at <= at), key=lambda u: u.used_at)
            session.add(
                InsulinDose(
                    user=user,
                    taken_at=at,
                    units=_round_to_step(units, PUMP_STEP),
                    insulin_type=InsulinType.RAPID,
                    kind=DoseKind.BOLUS,
                    site_use=current_set,
                )
            )

    session.add_all(
        [
            Reminder(
                user=user,
                kind=ReminderKind.SET_CHANGE,
                title="Change infusion set",
                interval_days=SET_CHANGE_DAYS,
            ),
            Reminder(
                user=user,
                kind=ReminderKind.SENSOR_CHANGE,
                title="Change CGM sensor",
                interval_days=SENSOR_CHANGE_DAYS,
            ),
        ]
    )
    session.flush()
    return user


def _rotate(
    session: Session,
    user: User,
    sites: Any,
    purpose: SitePurpose,
    first: datetime,
    last: datetime,
    every_days: int,
) -> list[SiteUse]:
    """Simple round-robin site changes for demo data (not the Stage 4 rotation algorithm)."""
    uses = []
    at = first
    while at <= last:
        use = SiteUse(user=user, site=next(sites), used_at=at, purpose=purpose)
        session.add(use)
        uses.append(use)
        at += timedelta(days=every_days)
    return uses


def _round_to_step(units: Decimal, step: Decimal) -> Decimal:
    return ((units / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step).quantize(step)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description="Seed a simulated pump + CGM demo user.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1, help="random seed for meals and sensor")
    parser.add_argument("--replace", action="store_true", help="replace an existing demo user")
    args = parser.parse_args(argv)

    engine = make_engine(get_settings().database_url)
    with make_session_factory(engine)() as session:
        # Check before simulating: the simulation takes several minutes.
        if not args.replace and UserRepository(session).get_by_email(DEMO_EMAIL) is not None:
            print(f"{DEMO_EMAIL} already exists; run again with --replace to rebuild it.")
            return 1
        print(f"Simulating {args.days} days (about 12 seconds per day)...")
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        data = simulate(args.days, start=today - timedelta(days=args.days), seed=args.seed)
        seed_demo_user(session, data, replace=args.replace)
        session.commit()
    print(
        f"Seeded {DEMO_EMAIL}: {len(data.readings)} readings, {len(data.meals)} meals, "
        f"{len(data.boluses)} boluses over {args.days} days."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
