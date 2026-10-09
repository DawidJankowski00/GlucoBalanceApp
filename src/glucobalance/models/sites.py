"""Body sites for injections, infusion sets and sensors, and each time one was used."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String
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
