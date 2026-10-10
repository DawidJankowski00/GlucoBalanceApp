"""Synthetic demo accounts: a pump + CGM user and a pens + glucometer user.

Everything here is made up. A small deterministic model draws a believable Type 1 day:
meals raise glucose, rapid insulin brings it down later, breakfast is slightly under-dosed
(so the pattern detectors have something to find) and a few nights dip low. Unlike
``seed.simulate`` it needs no optional libraries and runs in well under a second, which is why
the public demo uses it. The same seed always gives the same data.
"""

import math
import random
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from itertools import cycle

from sqlalchemy.orm import Session

from glucobalance.models import (
    CarbEntry,
    DeliveryMode,
    DoseKind,
    GlucoseReading,
    GlucoseTag,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    ReadingSource,
    SettingsTimeBlock,
    SitePurpose,
    SiteRegion,
    SiteUse,
    User,
    UserSettings,
)
from glucobalance.reminder_service import ensure_default_reminders
from glucobalance.repositories import GlucoseRepository, UserRepository
from glucobalance.seed import DEMO_EMAIL, SimulatedData, ensure_body_sites, seed_demo_user

PUMP_EMAIL = DEMO_EMAIL
PENS_EMAIL = "demo-pens-glucometer@example.com"
DEMO_EMAILS = frozenset({PUMP_EMAIL, PENS_EMAIL})
DEMO_DAYS = 21
STEP_MINUTES = 5

# (hour, minute, grams) of the usual meals, and the carb ratio used to dose them.
MEALS = ((7, 30, 55), (12, 30, 60), (18, 30, 70))
CARB_RATIO = 10
SENSITIVITY = 45  # mg/dL per unit
BREAKFAST_UNDERDOSE = 0.8
# Peak effects in mg/dL. A carb bump peaks after 60 minutes and an insulin dip after 105, so the
# dip needs about 0.57 of the rise per unit of area to cancel it; these two values balance for a
# correctly dosed meal (carb ratio 10, sensitivity 45), so glucose settles back to the baseline.
CARB_RISE = 3.0
INSULIN_FALL = 0.38
DOSE_STEP = Decimal("0.05")


def _peak(minutes: float, at: float) -> float:
    """A smooth bump that is 0 at 0 minutes, 1 at ``at`` minutes and fades after."""
    if minutes <= 0:
        return 0.0
    x = minutes / at
    return x * math.exp(1 - x)


class DemoDay:
    """The meals and doses of one synthetic day, in UTC."""

    def __init__(self, midnight: datetime, rng: random.Random) -> None:
        self.midnight = midnight
        self.meals: list[tuple[datetime, Decimal, Decimal]] = []
        for hour, minute, grams in MEALS:
            at = midnight + timedelta(hours=hour, minutes=minute + rng.randint(-20, 20))
            carbs = Decimal(max(20, round(grams + rng.gauss(0, 8))))
            units = float(carbs) / CARB_RATIO * (BREAKFAST_UNDERDOSE if hour == 7 else 1.0)
            dose = (Decimal(str(units)) / DOSE_STEP).quantize(Decimal(1)) * DOSE_STEP
            self.meals.append((at, carbs, dose.quantize(DOSE_STEP)))
        self.night_low = rng.random() < 0.2


def build_days(days: int, end: datetime, seed: int) -> list[DemoDay]:
    """One ``DemoDay`` per day for the ``days`` days before ``end``'s date."""
    rng = random.Random(seed)
    last_midnight = end.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return [DemoDay(last_midnight - timedelta(days=days - i), rng) for i in range(days)]


def glucose_at(at: datetime, days: list[DemoDay], noise: float) -> int:
    """Glucose in mg/dL at ``at``: baseline + meal rises - insulin falls + night dips."""
    value = 118.0 + noise
    for day in days:
        for eaten, grams, units in day.meals:
            minutes = (at - eaten).total_seconds() / 60
            if 0 < minutes < 600:
                value += float(grams) * CARB_RISE * _peak(minutes, 60)
                value -= float(units) * SENSITIVITY * INSULIN_FALL * _peak(minutes, 105)
        if day.night_low:
            minutes = (at - (day.midnight + timedelta(hours=3))).total_seconds() / 60
            value -= 75 * math.exp(-((minutes / 70) ** 2))
    return round(min(320.0, max(42.0, value)))


def _noise_series(count: int, rng: random.Random) -> list[float]:
    """A slow random walk that keeps pulling back to 0, so days differ a little."""
    noise, current = [], 0.0
    for _ in range(count):
        current = 0.96 * current + rng.gauss(0, 2.2)
        noise.append(current)
    return noise


def synthetic_pump_data(days: int = DEMO_DAYS, *, end: datetime, seed: int = 7) -> SimulatedData:
    """CGM readings every 5 minutes, meals and boluses, in the shape the real seed uses."""
    plan = build_days(days, end, seed)
    start = plan[0].midnight
    steps = days * 24 * 60 // STEP_MINUTES
    noise = _noise_series(steps, random.Random(seed + 1))
    times = [start + timedelta(minutes=STEP_MINUTES * i) for i in range(steps)]
    readings = [(at, glucose_at(at, plan, noise[i])) for i, at in enumerate(times)]
    meals = [(at, grams) for day in plan for at, grams, _ in day.meals]
    boluses = [(at, units) for day in plan for at, _, units in day.meals]
    return SimulatedData(readings=readings, meals=meals, boluses=boluses)


def seed_pump_user(session: Session, *, end: datetime, replace: bool = True) -> User:
    """The pump + CGM demo user (reminders included). Flushes, does not commit."""
    user = seed_demo_user(session, synthetic_pump_data(end=end), replace=replace)
    assert user.settings is not None
    user.settings.timezone = "Europe/Warsaw"
    user.display_name = "Demo: pump and CGM"
    ensure_default_reminders(session, user, now=end)
    session.flush()
    return user


def seed_pens_user(session: Session, *, end: datetime, replace: bool = True) -> User:
    """The pens + glucometer demo user: a few finger-stick readings a day, pen doses, sites."""
    users = UserRepository(session)
    existing = users.get_by_email(PENS_EMAIL)
    if existing is not None:
        if not replace:
            raise ValueError(f"demo user {PENS_EMAIL} already exists (use replace=True)")
        session.delete(existing)
        session.flush()
        session.expunge_all()

    user = users.add(User(email=PENS_EMAIL, display_name="Demo: pens and glucometer"))
    settings = UserSettings(
        user=user,
        delivery_mode=DeliveryMode.PENS,
        monitoring_mode=MonitoringMode.GLUCOMETER,
        max_bolus_units=Decimal("12"),
        dose_step_units=Decimal("0.5"),
        timezone="Europe/Warsaw",
        clinician_contact="Demo diabetes clinic (synthetic)",
    )
    settings.time_blocks = [
        SettingsTimeBlock(start_time=time(0, 0), icr_grams_per_unit=Decimal("10"), isf_mgdl=45)
    ]
    session.add(settings)

    plan = build_days(DEMO_DAYS, end, seed=11)
    rng = random.Random(12)
    readings: list[GlucoseReading] = []
    sites = ensure_body_sites(session)
    rapid_sites = cycle([s for s in sites if s.region is SiteRegion.ABDOMEN])
    long_sites = cycle([s for s in sites if s.region is SiteRegion.THIGH])
    half = Decimal("0.5")

    def reading(at: datetime, tag: GlucoseTag) -> None:
        readings.append(
            GlucoseReading(
                user=user,
                measured_at=at,
                value_mgdl=glucose_at(at, plan, rng.gauss(0, 6)),
                source=ReadingSource.MANUAL,
                tag=tag,
            )
        )

    def inject(at: datetime, units: Decimal, kind: DoseKind, site_iter: object) -> None:
        purpose = (
            SitePurpose.LONG_INJECTION if kind is DoseKind.BASAL else SitePurpose.RAPID_INJECTION
        )
        insulin = InsulinType.LONG if kind is DoseKind.BASAL else InsulinType.RAPID
        use = SiteUse(user=user, site=next(site_iter), used_at=at, purpose=purpose)  # type: ignore[call-overload]
        session.add(use)
        session.add(
            InsulinDose(
                user=user, taken_at=at, units=units, insulin_type=insulin, kind=kind, site_use=use
            )
        )

    for day in plan:
        reading(day.midnight + timedelta(hours=6, minutes=50), GlucoseTag.FASTING)
        for eaten, grams, units in day.meals:
            reading(eaten - timedelta(minutes=10), GlucoseTag.BEFORE_MEAL)
            reading(eaten + timedelta(hours=2), GlucoseTag.AFTER_MEAL)
            session.add(CarbEntry(user=user, eaten_at=eaten, grams=grams))
            pen_units = max(half, (units / half).quantize(Decimal(1)) * half)
            inject(eaten, pen_units, DoseKind.BOLUS, rapid_sites)
        reading(day.midnight + timedelta(hours=21, minutes=45), GlucoseTag.BEDTIME)
        inject(day.midnight + timedelta(hours=21), Decimal("18"), DoseKind.BASAL, long_sites)
    GlucoseRepository(session).add_new(readings)
    session.flush()
    ensure_default_reminders(session, user, now=end)
    return user


def seed_demo_users(
    session: Session, *, end: datetime | None = None, replace: bool = False
) -> None:
    """Create (or, with ``replace``, rebuild) both demo users. Does not commit."""
    end = end or datetime.now(UTC)
    users = UserRepository(session)
    if replace or users.get_by_email(PUMP_EMAIL) is None:
        seed_pump_user(session, end=end)
    if replace or users.get_by_email(PENS_EMAIL) is None:
        seed_pens_user(session, end=end)


def main() -> int:  # pragma: no cover - thin CLI wrapper
    from glucobalance.config import get_settings
    from glucobalance.db import make_engine, make_session_factory

    engine = make_engine(get_settings().database_url)
    with make_session_factory(engine)() as session:
        seed_demo_users(session, replace=True)
        session.commit()
    print("Demo users rebuilt: pump + CGM and pens + glucometer (synthetic data).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
