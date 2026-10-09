"""Hypo treatments: what was taken to bring a low glucose up."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.glucose import GlucoseReading
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class HypoTreatmentKind(StrEnum):
    GLUCOSE_TABLETS = "glucose_tablets"
    JUICE = "juice"
    SWEETS = "sweets"
    FOOD = "food"
    GLUCAGON = "glucagon"
    OTHER = "other"


class HypoTreatment(Base):
    __tablename__ = "hypo_treatments"
    __table_args__ = (
        CheckConstraint("carbs_grams IS NULL OR carbs_grams > 0", name="carbs_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    treated_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    treatment: Mapped[HypoTreatmentKind] = mapped_column(str_enum(HypoTreatmentKind))
    carbs_grams: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    # The low reading this treatment answers, when one was logged shortly before.
    reading_id: Mapped[int | None] = mapped_column(
        ForeignKey("glucose_readings.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(500))

    user: Mapped[User] = relationship()
    reading: Mapped[GlucoseReading | None] = relationship()
