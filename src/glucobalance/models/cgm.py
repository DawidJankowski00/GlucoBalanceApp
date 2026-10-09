"""A user's CGM connection: which source, its login, and how the last polls went."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class CGMSourceKind(StrEnum):
    LIBRELINKUP = "librelinkup"
    SIMULATOR = "simulator"


class GlucoseAlertKind(StrEnum):
    LOW = "low"
    HIGH = "high"
    FALLING_FAST = "falling_fast"
    STALE = "stale"


class CGMConnection(Base):
    """One per user. Passwords and tokens are stored only encrypted (see ``cgm.crypto``)."""

    __tablename__ = "cgm_connections"
    __table_args__ = (
        CheckConstraint("poll_minutes BETWEEN 1 AND 5", name="poll_minutes_range"),
        CheckConstraint("failure_count >= 0", name="failure_count_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    source: Mapped[CGMSourceKind] = mapped_column(str_enum(CGMSourceKind))
    enabled: Mapped[bool] = mapped_column(default=False)
    poll_minutes: Mapped[int] = mapped_column(default=5)

    # LibreLinkUp follower account (not the account of the FreeStyle Libre app).
    email: Mapped[str | None] = mapped_column(String(320))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    server: Mapped[str] = mapped_column(String(8), default="io")
    auto_accept_terms: Mapped[bool] = mapped_column(default=True)
    # The shared patient to follow when the account follows more than one.
    patient_id: Mapped[str | None] = mapped_column(String(64))
    reconnect_requested: Mapped[bool] = mapped_column(default=False)

    # Cached login, reused until it expires.
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    account_id: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str | None] = mapped_column(String(16))
    api_version: Mapped[str | None] = mapped_column(String(16))

    # Polling state.
    last_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reading_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    failure_count: Mapped[int] = mapped_column(default=0)
    retry_after: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # The alert currently in force, so one episode notifies once.
    alert_kind: Mapped[GlucoseAlertKind | None] = mapped_column(str_enum(GlucoseAlertKind))
    alert_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()
