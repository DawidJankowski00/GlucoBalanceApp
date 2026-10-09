"""Insulin doses: boluses, corrections and basal (long-acting or pump basal)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.sites import SiteUse
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class InsulinType(StrEnum):
    RAPID = "rapid"
    LONG = "long"


class DoseKind(StrEnum):
    BOLUS = "bolus"
    CORRECTION = "correction"
    BASAL = "basal"


class InsulinDose(Base):
    __tablename__ = "insulin_doses"
    __table_args__ = (CheckConstraint("units > 0", name="units_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    taken_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    units: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    insulin_type: Mapped[InsulinType] = mapped_column(str_enum(InsulinType))
    kind: Mapped[DoseKind] = mapped_column(str_enum(DoseKind))
    site_use_id: Mapped[int | None] = mapped_column(ForeignKey("site_uses.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship()
    site_use: Mapped[SiteUse | None] = relationship()
