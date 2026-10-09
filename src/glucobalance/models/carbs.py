"""Carbohydrate entries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime
from glucobalance.models.user import User


class CarbEntry(Base):
    __tablename__ = "carb_entries"
    __table_args__ = (CheckConstraint("grams > 0", name="grams_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    eaten_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    grams: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    description: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship()


class FavouriteMeal(Base):
    """A saved meal (name and carbs) that can be logged again in one tap."""

    __tablename__ = "favourite_meals"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        CheckConstraint("grams > 0", name="grams_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    grams: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    description: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship()
