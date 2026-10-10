"""The assistant's conversation memory and the adjustment suggestions waiting for a decision."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import utc_now


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AssistantMessage(Base):
    """One chat turn kept as memory. Only what the user and the assistant said is stored; the
    tool calls of a turn are not, so old data never goes back to the model stale. A blocked
    reply is stored as the block notice, never as the model's text."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    blocked: Mapped[bool] = mapped_column(default=False, server_default="0")


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class StoredSuggestion(Base):
    """A setting change the user has been asked to accept or reject (see ``adjustments``)."""

    __tablename__ = "adjustment_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    pattern: Mapped[str] = mapped_column(String(32))
    block_start: Mapped[time]
    setting: Mapped[str] = mapped_column(String(8))
    current_value: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    proposed_value: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[SuggestionStatus] = mapped_column(
        str_enum(SuggestionStatus), default=SuggestionStatus.PENDING
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
