"""Reminders. Only the basic fields for now; scheduling rules arrive in Stage 5."""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class ReminderKind(StrEnum):
    SET_CHANGE = "set_change"
    RESERVOIR = "reservoir"
    LONG_ACTING_DOSE = "long_acting_dose"
    PEN_NEEDLE = "pen_needle"
    PEN_EXPIRY = "pen_expiry"
    GLUCOSE_CHECK = "glucose_check"
    SENSOR_CHANGE = "sensor_change"
    CUSTOM = "custom"


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint("interval_days IS NULL OR interval_days > 0", name="interval_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ReminderKind] = mapped_column(str_enum(ReminderKind))
    title: Mapped[str] = mapped_column(String(100))
    interval_days: Mapped[int | None]
    time_of_day: Mapped[time | None]
    next_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User] = relationship()
