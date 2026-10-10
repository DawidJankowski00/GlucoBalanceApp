"""The forecast's input, and synthetic patients to train and test it on.

A ``History`` holds plain tuples in mg/dL, grams and units, the same shape as the simulator
output in ``glucobalance.seed`` (``SimulatedData``). The database, simglucose and the
synthetic generator below all produce it, so the feature code never sees an ORM object.

The synthetic generator is a small, deliberately simple physiology model, not a validated
simulator. It exists so the experiment, the tests and CI run in seconds without the optional
simglucose group. Glucose moves each minute by:

- carbs: absorbed along a gamma-shaped curve (peak after about 40 minutes), each gram raising
  glucose by the carb sensitivity (ISF / ICR);
- insulin: acting along a slower gamma curve (peak after about 55 minutes), each unit lowering
  glucose by the ISF;
- a basal mismatch that drifts slowly, a dawn rise, and random noise;
- a weak pull back towards a resting level, so the trace does not wander off;
- sensor noise on top of the true value.

Meals are given a bolus that is sometimes too small, too large, late or missing, and there are
unbolused snacks and occasional corrections. That gives the model highs and lows to learn from.
"""

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

SAMPLE_MINUTES = 5
CARB_PEAK_MINUTES = 40.0
INSULIN_PEAK_MINUTES = 55.0
MIN_TRUE_MGDL = 40.0
MAX_TRUE_MGDL = 400.0
# A weak pull back towards a resting level, standing in for a roughly right basal rate.
SETTLE_TOWARDS_MGDL = 120.0
SETTLE_PER_MINUTE = 0.0015


@dataclass(frozen=True, slots=True)
class History:
    """Readings (time, mg/dL), carbs (time, grams) and rapid boluses (time, units), all UTC."""

    readings: tuple[tuple[datetime, int], ...]
    carbs: tuple[tuple[datetime, float], ...] = ()
    boluses: tuple[tuple[datetime, float], ...] = ()


@dataclass(frozen=True, slots=True)
class PatientProfile:
    """The made-up settings of one synthetic patient."""

    isf: float  # mg/dL per unit
    icr: float  # grams per unit
    bolus_error: float  # standard deviation of the bolus factor (1.0 is a perfect bolus)
    missed_bolus_chance: float
    snack_chance: float


def gamma_rate(minutes: float, peak: float) -> float:
    """Share of the total effect that happens in minute ``minutes`` (sums to about 1)."""
    if minutes < 0:
        return 0.0
    return minutes / peak**2 * math.exp(-minutes / peak)


def random_profile(rng: random.Random) -> PatientProfile:
    return PatientProfile(
        isf=rng.uniform(35, 60),
        icr=rng.uniform(8, 14),
        bolus_error=rng.uniform(0.12, 0.25),
        missed_bolus_chance=rng.uniform(0.03, 0.1),
        snack_chance=rng.uniform(0.2, 0.5),
    )


def _events(
    rng: random.Random, start: datetime, days: int, profile: PatientProfile
) -> tuple[list[tuple[datetime, float]], list[tuple[datetime, float]]]:
    """Meals, snacks and their boluses for ``days`` days."""
    carbs: list[tuple[datetime, float]] = []
    boluses: list[tuple[datetime, float]] = []
    for day in range(days):
        midnight = start + timedelta(days=day)
        for hour, low, high in ((7.5, 30, 70), (13.0, 40, 90), (19.0, 40, 90)):
            eaten = midnight + timedelta(hours=hour + rng.gauss(0, 0.7))
            grams = round(rng.uniform(low, high))
            carbs.append((eaten, float(grams)))
            if rng.random() < profile.missed_bolus_chance:
                continue
            factor = max(rng.gauss(1.1, profile.bolus_error), 0.4)
            delay = rng.choice((-15, 0, 0, 0, 10, 20))  # pre-bolus, on time, or late
            units = round(grams / profile.icr * factor * 20) / 20
            boluses.append((eaten + timedelta(minutes=delay), units))
        if rng.random() < profile.snack_chance:
            snack = midnight + timedelta(hours=rng.uniform(15, 22))
            carbs.append((snack, float(round(rng.uniform(10, 30)))))
    carbs.sort()
    boluses.sort()
    return carbs, boluses


def synthetic_history(
    days: int, seed: int, *, start: datetime | None = None, profile: PatientProfile | None = None
) -> History:
    """``days`` days of readings every 5 minutes for one synthetic patient."""
    rng = random.Random(seed)
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    profile = profile or random_profile(rng)
    planned_carbs, planned_boluses = _events(rng, start, days, profile)
    carb_effect = profile.isf / profile.icr  # mg/dL per gram

    # Events by start minute; "active" keeps those still acting (gamma curves fade by ~7 h).
    pending_carbs = [(int((at - start).total_seconds() // 60), g) for at, g in planned_carbs]
    pending_boluses = [(int((at - start).total_seconds() // 60), u) for at, u in planned_boluses]
    active_carbs: list[tuple[int, float]] = []
    active_boluses: list[tuple[int, float]] = []
    carbs: list[tuple[datetime, float]] = []
    boluses: list[tuple[datetime, float]] = []
    window = 7 * 60

    glucose = rng.uniform(100, 160)
    drift = 0.0  # basal mismatch in mg/dL per minute
    noise = 0.0
    readings: list[tuple[datetime, int]] = []
    last_correction = -10_000
    last_treatment = -10_000
    for minute in range(days * 24 * 60):
        now = start + timedelta(minutes=minute)
        while pending_carbs and pending_carbs[0][0] <= minute:
            at, grams = pending_carbs.pop(0)
            active_carbs.append((at, grams))
            carbs.append((start + timedelta(minutes=at), grams))
        while pending_boluses and pending_boluses[0][0] <= minute:
            at, units = pending_boluses.pop(0)
            active_boluses.append((at, units))
            boluses.append((start + timedelta(minutes=at), units))
        active_carbs = [(at, g) for at, g in active_carbs if minute - at < window]
        active_boluses = [(at, u) for at, u in active_boluses if minute - at < window]

        rise = sum(
            g * carb_effect * gamma_rate(minute - at, CARB_PEAK_MINUTES) for at, g in active_carbs
        )
        fall = sum(
            u * profile.isf * gamma_rate(minute - at, INSULIN_PEAK_MINUTES)
            for at, u in active_boluses
        )
        hour = (minute % 1440) / 60
        dawn = 0.12 * math.exp(-(((hour - 5.5) / 1.5) ** 2))
        drift = 0.995 * drift + rng.gauss(0, 0.004)
        noise = 0.9 * noise + rng.gauss(0, 0.08)
        settle = SETTLE_PER_MINUTE * (SETTLE_TOWARDS_MGDL - glucose)
        glucose += rise - fall + dawn + drift + noise + settle
        glucose = min(max(glucose, MIN_TRUE_MGDL), MAX_TRUE_MGDL)

        # A correction now and then when high, like a person checking their CGM.
        if glucose > 230 and minute - last_correction > 180 and rng.random() < 0.01:
            units = round((glucose - 140) / profile.isf * rng.uniform(0.6, 1.0) * 20) / 20
            active_boluses.append((minute, units))
            boluses.append((now, units))
            last_correction = minute
        # A low is treated with 15 g of fast carbs, then given time to work.
        if glucose < 65 and minute - last_treatment > 20 and rng.random() < 0.2:
            active_carbs.append((minute, 15.0))
            carbs.append((now, 15.0))
            last_treatment = minute

        if minute % SAMPLE_MINUTES == 0:
            sensed = glucose + rng.gauss(0, 4)
            readings.append((now, round(min(max(sensed, MIN_TRUE_MGDL), MAX_TRUE_MGDL))))
    return History(
        readings=tuple(readings),
        carbs=tuple(sorted(carbs)),
        boluses=tuple(sorted(boluses)),
    )
