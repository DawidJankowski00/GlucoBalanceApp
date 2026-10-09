"""Free-text notes on the timeline (sport, illness, stress, and so on)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime
from glucobalance.models.user import User


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    noted_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    text: Mapped[str] = mapped_column(Text)

    user: Mapped[User] = relationship()
