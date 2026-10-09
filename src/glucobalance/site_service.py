"""Site rotation for pump and pen users.

This module gathers what the ranking needs from the database (last uses, blocks, weights),
calls the owner's pure ``rotation.rank_sites`` and records what the user did. Pump users rotate
one site per infusion set change; pen users keep two separate rotations, one for rapid-acting
and one for long-acting insulin. The feature flags decide which.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError, check_entry_time
from glucobalance.features import FeatureFlags, SiteRotationUnit, feature_flags
from glucobalance.models import (
    BodySite,
    SiteBlock,
    SitePreference,
    SitePurpose,
    SiteUse,
    User,
    UserSettings,
)
from glucobalance.repositories import SiteRepository
from glucobalance.rotation import SiteState, rank_sites
from glucobalance.sitemap import site_label

MIN_WEIGHT = Decimal(0)
MAX_WEIGHT = Decimal(2)
REASON_MAX_LENGTH = 100

PURPOSE_LABELS = {
    SitePurpose.INFUSION_SET: "Infusion set",
    SitePurpose.RAPID_INJECTION: "Rapid-acting injection",
    SitePurpose.LONG_INJECTION: "Long-acting injection",
    SitePurpose.CGM_SENSOR: "CGM sensor",
}


class SiteError(EntryError):
    """The site action is not allowed. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class SetChangeStatus:
    """When the infusion set was last changed and when the next change is due."""

    last_change: datetime | None
    next_due: datetime | None
    days_left: int | None
    overdue: bool


def purposes_for(flags: FeatureFlags) -> list[SitePurpose]:
    """The rotations this user keeps: one for a pump, two for pens."""
    if flags.site_rotation_unit is SiteRotationUnit.PER_SET_CHANGE:
        return [SitePurpose.INFUSION_SET]
    if flags.separate_long_acting_rotation:
        return [SitePurpose.RAPID_INJECTION, SitePurpose.LONG_INJECTION]
    return [SitePurpose.RAPID_INJECTION]


def _settings(user: User) -> UserSettings:
    if user.settings is None:
        raise SiteError("Finish your settings first.")
    return user.settings


def _site(repo: SiteRepository, code: str) -> BodySite:
    site = repo.get_by_code(code)
    if site is None:
        raise SiteError(f"Unknown site: {code}.")
    return site


def site_states(
    session: Session, user: User, purpose: SitePurpose, *, now: datetime
) -> list[SiteState]:
    """Every site with its last use for ``purpose``, its block at ``now`` and its weight."""
    repo = SiteRepository(session)
    last_used = repo.last_used(user.id, purpose)
    blocked = {block.site_id for block in repo.active_blocks(user.id, now)}
    weights = repo.weights(user.id)
    return [
        SiteState(
            code=site.code,
            last_used=last_used.get(site.id),
            blocked=site.id in blocked,
            weight=float(weights[site.id].weight) if site.id in weights else 1.0,
        )
        for site in repo.all()
    ]


def suggestions(session: Session, user: User, purpose: SitePurpose, *, now: datetime) -> list[str]:
    """Site codes for ``purpose``, best first, without blocked or avoided sites."""
    rest_days = _settings(user).site_rest_days
    return rank_sites(site_states(session, user, purpose, now=now), now, rest_days)


def log_site_use(
    session: Session,
    user: User,
    code: str,
    purpose: SitePurpose,
    *,
    now: datetime,
    used_at: datetime | None = None,
) -> SiteUse:
    """Record that ``code`` was used for ``purpose``. Never commits."""
    settings = _settings(user)
    flags = feature_flags(settings.delivery_mode, settings.monitoring_mode)
    if purpose not in purposes_for(flags):
        raise SiteError(
            f"{PURPOSE_LABELS[purpose]} does not match your settings"
            f" ({settings.delivery_mode.value})."
        )
    when = used_at or now
    check_entry_time(when, now)
    repo = SiteRepository(session)
    site = _site(repo, code)
    if any(block.site_id == site.id for block in repo.active_blocks(user.id, when)):
        raise SiteError(f"{site_label(code)} is marked not available.")
    return repo.add_use(SiteUse(user_id=user.id, site=site, used_at=when, purpose=purpose))


def block_site(
    session: Session,
    user: User,
    code: str,
    *,
    now: datetime,
    until: datetime | None,
    reason: str | None,
) -> SiteBlock:
    """Mark a site not available until ``until`` (or until removed). Replaces a current block."""
    if until is not None and until <= now:
        raise SiteError("The end date must be in the future.")
    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > REASON_MAX_LENGTH:
        raise SiteError(f"Keep the reason under {REASON_MAX_LENGTH} characters.")
    repo = SiteRepository(session)
    site = _site(repo, code)
    _end_blocks(repo, user, site, now)
    return repo.add_block(
        SiteBlock(user_id=user.id, site=site, blocked_at=now, until=until, reason=reason)
    )


def unblock_site(session: Session, user: User, code: str, *, now: datetime) -> None:
    """Make a site available again from ``now``. The old block stays as history."""
    repo = SiteRepository(session)
    _end_blocks(repo, user, _site(repo, code), now)
    session.flush()


def _end_blocks(repo: SiteRepository, user: User, site: BodySite, now: datetime) -> None:
    for block in repo.active_blocks(user.id, now):
        if block.site_id == site.id:
            block.until = now


def blocked_sites(session: Session, user: User, *, now: datetime) -> Sequence[SiteBlock]:
    return SiteRepository(session).active_blocks(user.id, now)


def set_weight(session: Session, user: User, code: str, weight: Decimal) -> SitePreference:
    """Store how much the user likes a site (0 avoids it, 1 is neutral, 2 prefers it)."""
    if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        raise SiteError("Choose a weight between 0 and 2.")
    repo = SiteRepository(session)
    site = _site(repo, code)
    preference = repo.weights(user.id).get(site.id)
    if preference is None:
        return repo.add_preference(SitePreference(user_id=user.id, site=site, weight=weight))
    preference.weight = weight
    session.flush()
    return preference


def set_change_status(session: Session, user: User, *, now: datetime) -> SetChangeStatus:
    """Days until the next infusion set change, from the last logged change."""
    interval = timedelta(days=_settings(user).set_change_days)
    last = SiteRepository(session).last_use(user.id, SitePurpose.INFUSION_SET)
    if last is None:
        return SetChangeStatus(None, None, None, overdue=False)
    next_due = last.used_at + interval
    remaining = (next_due - now).total_seconds()
    if remaining <= 0:
        return SetChangeStatus(last.used_at, next_due, 0, overdue=True)
    return SetChangeStatus(last.used_at, next_due, math.ceil(remaining / 86400), overdue=False)
