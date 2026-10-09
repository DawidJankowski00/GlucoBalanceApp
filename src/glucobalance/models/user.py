"""The user and their treatment settings."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum


def utc_now() -> datetime:
    return datetime.now(UTC)


class DeliveryMode(StrEnum):
    PUMP = "pump"
    PENS = "pens"


class MonitoringMode(StrEnum):
    GLUCOMETER = "glucometer"
    CGM = "cgm"


class DisplayUnit(StrEnum):
    MGDL = "mg/dL"
    MMOLL = "mmol/L"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSettings(Base):
    """The two onboarding switches plus the shared treatment settings (glucose in mg/dL)."""

    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("target_low_mgdl < target_high_mgdl", name="target_range_order"),
        CheckConstraint("target_low_mgdl > 0", name="target_low_positive"),
        CheckConstraint("insulin_action_minutes > 0", name="insulin_action_positive"),
        CheckConstraint("max_bolus_units > 0", name="max_bolus_positive"),
        CheckConstraint("dose_step_units > 0", name="dose_step_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    delivery_mode: Mapped[DeliveryMode] = mapped_column(str_enum(DeliveryMode))
    monitoring_mode: Mapped[MonitoringMode] = mapped_column(str_enum(MonitoringMode))
    display_unit: Mapped[DisplayUnit] = mapped_column(
        str_enum(DisplayUnit), default=DisplayUnit.MGDL
    )
    target_low_mgdl: Mapped[int] = mapped_column(default=70)
    target_high_mgdl: Mapped[int] = mapped_column(default=180)
    insulin_action_minutes: Mapped[int] = mapped_column(default=240)
    max_bolus_units: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    dose_step_units: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.5"))
    clinician_contact: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="settings")
    time_blocks: Mapped[list[SettingsTimeBlock]] = relationship(
        back_populates="settings",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SettingsTimeBlock.start_time",
    )


class SettingsTimeBlock(Base):
    """ICR and ISF that apply from ``start_time`` until the next block starts."""

    __tablename__ = "settings_time_blocks"
    __table_args__ = (
        UniqueConstraint("settings_id", "start_time"),
        CheckConstraint("icr_grams_per_unit > 0", name="icr_positive"),
        CheckConstraint("isf_mgdl > 0", name="isf_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    settings_id: Mapped[int] = mapped_column(ForeignKey("user_settings.id", ondelete="CASCADE"))
    start_time: Mapped[time]
    icr_grams_per_unit: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    isf_mgdl: Mapped[int]

    settings: Mapped[UserSettings] = relationship(back_populates="time_blocks")
