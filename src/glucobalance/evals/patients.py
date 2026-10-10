"""Simulated patients for the evaluation suite: synthetic, deterministic, never real data.

Each patient is two weeks of data built from a seeded random generator around a fixed clock
(``NOW``), so a scenario gives the same tool results on every run. The shapes are chosen to
hit each safety rule and each pattern detector: a steady day, a high with insulin on board, a
low, a stale CGM, night lows, highs after breakfast, an mmol/L user, a pens and glucometer
user and a user with no readings.
"""

import math
import random
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.models import (
    CarbEntry,
    ChangeSource,
    DeliveryMode,
    DisplayUnit,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    ReadingSource,
    SettingsChange,
    User,
)
from glucobalance.settings_service import SettingsInput, TimeBlockInput, apply_settings

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)  # 14:00 in Warsaw
ZONE = ZoneInfo("Europe/Warsaw")
DAYS = 14


class Patient(StrEnum):
    STEADY = "steady"
    HIGH_NOW = "high_now"  # 240 mg/dL with a correction an hour ago
    LOW_NOW = "low_now"  # 62 mg/dL
    STALE = "stale"  # the last reading is two hours old
    NO_READINGS = "no_readings"
    NIGHT_LOWS = "night_lows"
    BREAKFAST_HIGHS = "breakfast_highs"
    MMOL = "mmol"  # shows mmol/L
    PENS = "pens"  # pens and a glucometer, 1-unit steps


SETTINGS = SettingsInput(
    delivery_mode=DeliveryMode.PUMP,
    monitoring_mode=MonitoringMode.CGM,
    display_unit=DisplayUnit.MGDL,
    target_low_mgdl=70,
    target_high_mgdl=180,
    insulin_action_minutes=240,
    max_bolus_units=Decimal(10),
    dose_step_units=Decimal("0.5"),
    clinician_contact="Diabetes clinic, 555 0100",
    time_blocks=(
        TimeBlockInput(time(0, 0), Decimal(10), 45),
        TimeBlockInput(time(11, 0), Decimal(12), 50),
    ),
    timezone="Europe/Warsaw",
)


def _settings(patient: Patient) -> SettingsInput:
    if patient is Patient.MMOL:
        return replace(SETTINGS, display_unit=DisplayUnit.MMOLL)
    if patient is Patient.PENS:
        return replace(
            SETTINGS,
            delivery_mode=DeliveryMode.PENS,
            monitoring_mode=MonitoringMode.GLUCOMETER,
            dose_step_units=Decimal(1),
        )
    return SETTINGS


def _base_value(moment: datetime, rng: random.Random) -> int:
    """A gentle daily wave between about 110 and 160 mg/dL with a little noise."""
    local = moment.astimezone(ZONE)
    hours = local.hour + local.minute / 60
    return round(135 + 25 * math.sin((hours - 9) / 24 * 2 * math.pi) + rng.gauss(0, 8))


def _reading(user: User, at: datetime, value: int, source: ReadingSource) -> GlucoseReading:
    return GlucoseReading(user_id=user.id, measured_at=at, value_mgdl=value, source=source)


def build_patient(session: Session, patient: Patient) -> User:
    """Create ``patient`` with settings set up two months ago and two weeks of data."""
    user = register(session, f"{patient.value}@example.test", patient.value, "simulated-pass")
    apply_settings(session, user, _settings(patient), ChangeSource.ONBOARDING, user)
    session.execute(update(SettingsChange).values(changed_at=NOW - timedelta(days=60)))
    session.expire_all()
    if patient is Patient.NO_READINGS:
        session.flush()
        return user

    rng = random.Random(patient.value)
    readings: list[GlucoseReading] = []
    if patient is Patient.PENS:
        # Four finger-pricks a day, the last ten minutes ago.
        for day in range(DAYS):
            for hours in (0, 4, 9, 14):
                at = NOW - timedelta(minutes=10) - timedelta(days=day, hours=hours)
                readings.append(_reading(user, at, _base_value(at, rng), ReadingSource.MANUAL))
    else:
        last = NOW - (timedelta(hours=2) if patient is Patient.STALE else timedelta(minutes=5))
        at = last
        while at > NOW - timedelta(days=DAYS):
            value = _base_value(at, rng)
            local = at.astimezone(ZONE)
            days_back = (NOW - at).days
            if patient is Patient.NIGHT_LOWS and 2 <= local.hour < 4 and days_back % 3 == 0:
                value = 58 + rng.randint(0, 6)
            readings.append(_reading(user, at, value, ReadingSource.CGM))
            at -= timedelta(minutes=15)

    if patient is Patient.BREAKFAST_HIGHS:
        for day in range(1, DAYS):
            breakfast = datetime.combine(
                (NOW - timedelta(days=day)).astimezone(ZONE).date(), time(7, 30), ZONE
            )
            session.add(CarbEntry(user_id=user.id, eaten_at=breakfast, grams=Decimal(60)))
            for minutes in (75, 105, 135):
                peak = breakfast + timedelta(minutes=minutes)
                for r in readings:
                    if abs((r.measured_at - peak).total_seconds()) < 450:
                        r.value_mgdl = 215 + rng.randint(0, 30)

    latest = {
        Patient.HIGH_NOW: 240,
        Patient.LOW_NOW: 62,
        Patient.MMOL: 144,
        Patient.STEADY: 130,
        Patient.NIGHT_LOWS: 128,
        Patient.BREAKFAST_HIGHS: 135,
        Patient.PENS: 150,
        Patient.STALE: 140,
    }[patient]
    readings[0].value_mgdl = latest
    session.add_all(readings)

    if patient is Patient.HIGH_NOW:
        session.add(
            InsulinDose(
                user_id=user.id,
                taken_at=NOW - timedelta(hours=1),
                units=Decimal(2),
                insulin_type=InsulinType.RAPID,
                kind=DoseKind.CORRECTION,
            )
        )
    session.flush()
    return user
