"""The log of every change to a user's treatment settings."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import utc_now


class ChangeSource(StrEnum):
    ONBOARDING = "onboarding"
    USER = "user"
    ASSISTANT_SUGGESTION = "assistant_suggestion"


class SettingsChange(Base):
    """One field that changed: who changed it, when, the old and new value, and through what.

    Values are stored as text (``"70"``, ``"pump"``, a JSON string for time blocks) so one
    table can hold every kind of setting. ``old_value`` is empty for the first value.
    """

    __tablename__ = "settings_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    source: Mapped[ChangeSource] = mapped_column(str_enum(ChangeSource))
