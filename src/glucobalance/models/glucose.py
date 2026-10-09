"""Glucose readings, always stored in mg/dL."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class ReadingSource(StrEnum):
    MANUAL = "manual"
    CGM = "cgm"
    SIMULATED = "simulated"


class GlucoseTag(StrEnum):
    FASTING = "fasting"
    BEFORE_MEAL = "before_meal"
    AFTER_MEAL = "after_meal"
    BEDTIME = "bedtime"
    NIGHT = "night"


class Trend(StrEnum):
    FALLING_FAST = "falling_fast"
    FALLING = "falling"
    STEADY = "steady"
    RISING = "rising"
    RISING_FAST = "rising_fast"


class GlucoseReading(Base):
    __tablename__ = "glucose_readings"
    __table_args__ = (
        # One reading per user, source and moment: makes CGM imports idempotent.
        UniqueConstraint("user_id", "source", "measured_at"),
        CheckConstraint("value_mgdl > 0", name="value_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    measured_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    value_mgdl: Mapped[int]
    source: Mapped[ReadingSource] = mapped_column(str_enum(ReadingSource))
    tag: Mapped[GlucoseTag | None] = mapped_column(str_enum(GlucoseTag))
    trend: Mapped[Trend | None] = mapped_column(str_enum(Trend))
    note: Mapped[str | None] = mapped_column(String(500))

    user: Mapped[User] = relationship()
