"""Body sites for injections, infusion sets and sensors, and each time one was used."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glucobalance.db import Base
from glucobalance.models.types import UTCDateTime, str_enum
from glucobalance.models.user import User


class SiteRegion(StrEnum):
    ABDOMEN = "abdomen"
    THIGH = "thigh"
    ARM = "arm"
    BUTTOCK = "buttock"


class BodySide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class BodyView(StrEnum):
    FRONT = "front"
    BACK = "back"


class SitePurpose(StrEnum):
    INFUSION_SET = "infusion_set"
    RAPID_INJECTION = "rapid_injection"
    LONG_INJECTION = "long_injection"
    CGM_SENSOR = "cgm_sensor"


class BodySite(Base):
    """One point or sub-zone on the body map. Shared reference data, not per user."""

    __tablename__ = "body_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    region: Mapped[SiteRegion] = mapped_column(str_enum(SiteRegion))
    side: Mapped[BodySide] = mapped_column(str_enum(BodySide))
    view: Mapped[BodyView] = mapped_column(str_enum(BodyView))
    zone: Mapped[str] = mapped_column(String(30), default="", server_default="")


class SiteUse(Base):
    __tablename__ = "site_uses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("body_sites.id"))
    used_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    purpose: Mapped[SitePurpose] = mapped_column(str_enum(SitePurpose))

    user: Mapped[User] = relationship()
    site: Mapped[BodySite] = relationship()


class SiteBlock(Base):
    """A site the user cannot use for now (bruise, sport) or ever (lump, scar, tattoo).

    ``until`` is the moment the block ends; ``None`` means it lasts until the user removes it.
    A block applies to every purpose: a bruised spot is bruised for any insulin.
    """

    __tablename__ = "site_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("body_sites.id"))
    blocked_at: Mapped[datetime] = mapped_column(UTCDateTime)
    until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reason: Mapped[str | None] = mapped_column(String(100))

    user: Mapped[User] = relationship()
    site: Mapped[BodySite] = relationship()


class SitePreference(Base):
    """How much the user likes a site: 0 avoids it, 1 is neutral, 2 is preferred."""

    __tablename__ = "site_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "site_id"),
        CheckConstraint("weight >= 0 AND weight <= 2", name="weight_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("body_sites.id"))
    weight: Mapped[Decimal] = mapped_column(Numeric(2, 1))

    user: Mapped[User] = relationship()
    site: Mapped[BodySite] = relationship()
