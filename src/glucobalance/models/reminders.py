"""Reminders (what is due and when), in-app notifications and browser push subscriptions."""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
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
    MISSED_DOSE = "missed_dose"
    HYPO_RECHECK = "hypo_recheck"
    CUSTOM = "custom"


class RuleType(StrEnum):
    """How the next due time is worked out (see ``reminder_rules``)."""

    EVERY_N_DAYS = "every_n_days"
    DAILY_AT = "daily_at"
    AFTER_EVENT = "after_event"


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint("interval_days IS NULL OR interval_days > 0", name="interval_positive"),
        CheckConstraint("delay_minutes IS NULL OR delay_minutes >= 0", name="delay_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ReminderKind] = mapped_column(str_enum(ReminderKind))
    title: Mapped[str] = mapped_column(String(100))
    rule_type: Mapped[RuleType] = mapped_column(
        str_enum(RuleType), default=RuleType.EVERY_N_DAYS, server_default="every_n_days"
    )
    interval_days: Mapped[int | None]
    # Daily rules: the wall-clock time. Every-N-days rules: an optional fixed time.
    time_of_day: Mapped[time | None]
    # After-event rules: minutes after the event.
    delay_minutes: Mapped[int | None]
    next_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User] = relationship()


class Notification(Base):
    """A message in the in-app notification centre (the fallback when push is not available)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reminder_id: Mapped[int | None] = mapped_column(ForeignKey("reminders.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class PushSubscription(Base):
    """One browser or phone that agreed to receive Web Push messages."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()
