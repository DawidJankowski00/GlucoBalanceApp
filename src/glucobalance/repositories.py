"""Repositories: the only place that builds database queries.

Each repository wraps a session. Repositories ``flush`` (send SQL, get ids) but never
``commit``; the caller decides when one unit of work is finished.
Time ranges are half-open: ``start <= t < end``.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from glucobalance.db import Base
from glucobalance.models import (
    BodySite,
    CarbEntry,
    FavouriteMeal,
    GlucoseReading,
    HypoTreatment,
    InsulinDose,
    Note,
    Reminder,
    SiteBlock,
    SitePreference,
    SitePurpose,
    SiteUse,
    User,
)


def _check_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("naive datetime in a time range: attach a timezone (use UTC)")


def _owner_id(reading: GlucoseReading) -> int:
    # A reading built with ``user=...`` has no user_id until it is flushed.
    return reading.user_id if reading.user_id is not None else reading.user.id


class Repository[M: Base]:
    """Shared ``add`` and ``get`` for one model class."""

    model: type[M]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: M) -> M:
        self.session.add(obj)
        self.session.flush()
        return obj

    def get(self, id: int) -> M | None:
        return self.session.get(self.model, id)


class UserRepository(Repository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalars(select(User).where(User.email == email)).one_or_none()


class GlucoseRepository(Repository[GlucoseReading]):
    model = GlucoseReading

    def between(self, user_id: int, start: datetime, end: datetime) -> Sequence[GlucoseReading]:
        _check_range(start, end)
        return self.session.scalars(
            select(GlucoseReading)
            .where(
                GlucoseReading.user_id == user_id,
                GlucoseReading.measured_at >= start,
                GlucoseReading.measured_at < end,
            )
            .order_by(GlucoseReading.measured_at)
        ).all()

    def latest(self, user_id: int) -> GlucoseReading | None:
        return self.session.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.user_id == user_id)
            .order_by(GlucoseReading.measured_at.desc())
            .limit(1)
        ).first()

    def recent(self, user_id: int, limit: int) -> Sequence[GlucoseReading]:
        """The newest ``limit`` readings, newest first."""
        return self.session.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.user_id == user_id)
            .order_by(GlucoseReading.measured_at.desc())
            .limit(limit)
        ).all()

    def latest_between(self, user_id: int, start: datetime, end: datetime) -> GlucoseReading | None:
        """The newest reading in ``[start, end)``, or None."""
        _check_range(start, end)
        return self.session.scalars(
            select(GlucoseReading)
            .where(
                GlucoseReading.user_id == user_id,
                GlucoseReading.measured_at >= start,
                GlucoseReading.measured_at < end,
            )
            .order_by(GlucoseReading.measured_at.desc())
            .limit(1)
        ).first()

    def add_new(self, readings: Iterable[GlucoseReading]) -> int:
        """Add readings not stored yet (same user, source and time); return how many were added.

        Makes imports idempotent: running the same CGM import twice adds nothing the second time.
        """
        batch = list(readings)
        if not batch:
            return 0
        times = [r.measured_at for r in batch]
        stored = {
            (user_id, source, measured_at)
            for user_id, source, measured_at in self.session.execute(
                select(
                    GlucoseReading.user_id, GlucoseReading.source, GlucoseReading.measured_at
                ).where(
                    GlucoseReading.user_id.in_({_owner_id(r) for r in batch}),
                    GlucoseReading.measured_at >= min(times),
                    GlucoseReading.measured_at <= max(times),
                )
            )
        }
        added = 0
        for r in batch:
            key = (_owner_id(r), r.source, r.measured_at)
            if key in stored:
                continue
            stored.add(key)
            self.session.add(r)
            added += 1
        self.session.flush()
        return added


class InsulinRepository(Repository[InsulinDose]):
    model = InsulinDose

    def between(self, user_id: int, start: datetime, end: datetime) -> Sequence[InsulinDose]:
        _check_range(start, end)
        return self.session.scalars(
            select(InsulinDose)
            .where(
                InsulinDose.user_id == user_id,
                InsulinDose.taken_at >= start,
                InsulinDose.taken_at < end,
            )
            .order_by(InsulinDose.taken_at)
        ).all()


class CarbRepository(Repository[CarbEntry]):
    model = CarbEntry

    def between(self, user_id: int, start: datetime, end: datetime) -> Sequence[CarbEntry]:
        _check_range(start, end)
        return self.session.scalars(
            select(CarbEntry)
            .where(
                CarbEntry.user_id == user_id,
                CarbEntry.eaten_at >= start,
                CarbEntry.eaten_at < end,
            )
            .order_by(CarbEntry.eaten_at)
        ).all()


class NoteRepository(Repository[Note]):
    model = Note

    def between(self, user_id: int, start: datetime, end: datetime) -> Sequence[Note]:
        _check_range(start, end)
        return self.session.scalars(
            select(Note)
            .where(Note.user_id == user_id, Note.noted_at >= start, Note.noted_at < end)
            .order_by(Note.noted_at)
        ).all()


class SiteRepository(Repository[BodySite]):
    model = BodySite

    def all(self) -> Sequence[BodySite]:
        return self.session.scalars(select(BodySite).order_by(BodySite.code)).all()

    def get_by_code(self, code: str) -> BodySite | None:
        return self.session.scalars(select(BodySite).where(BodySite.code == code)).one_or_none()

    def add_use(self, use: SiteUse) -> SiteUse:
        self.session.add(use)
        self.session.flush()
        return use

    def last_used(self, user_id: int, purpose: SitePurpose) -> dict[int, datetime]:
        """Map each site id to the last time it was used for ``purpose`` (unused sites absent)."""
        rows = self.session.execute(
            select(SiteUse.site_id, func.max(SiteUse.used_at))
            .where(SiteUse.user_id == user_id, SiteUse.purpose == purpose)
            .group_by(SiteUse.site_id)
        )
        return {site_id: used_at for site_id, used_at in rows}

    def last_use(self, user_id: int, purpose: SitePurpose) -> SiteUse | None:
        """The most recent use for ``purpose``, or ``None``."""
        return self.session.scalars(
            select(SiteUse)
            .where(SiteUse.user_id == user_id, SiteUse.purpose == purpose)
            .order_by(SiteUse.used_at.desc(), SiteUse.id.desc())
            .limit(1)
        ).one_or_none()

    def use_counts(self, user_id: int, start: datetime, end: datetime) -> dict[str, int]:
        """Uses per site code in ``[start, end)``, any purpose (unused sites absent)."""
        _check_range(start, end)
        rows = self.session.execute(
            select(BodySite.code, func.count(SiteUse.id))
            .join(SiteUse.site)
            .where(SiteUse.user_id == user_id, SiteUse.used_at >= start, SiteUse.used_at < end)
            .group_by(BodySite.code)
        )
        return {code: count for code, count in rows}

    def active_blocks(self, user_id: int, now: datetime) -> Sequence[SiteBlock]:
        """Blocks in force at ``now`` (started, and not yet ended), ordered by site code."""
        return self.session.scalars(
            select(SiteBlock)
            .join(SiteBlock.site)
            .where(
                SiteBlock.user_id == user_id,
                SiteBlock.blocked_at <= now,
                (SiteBlock.until.is_(None)) | (SiteBlock.until > now),
            )
            .order_by(BodySite.code, SiteBlock.id)
        ).all()

    def add_block(self, block: SiteBlock) -> SiteBlock:
        self.session.add(block)
        self.session.flush()
        return block

    def weights(self, user_id: int) -> dict[int, SitePreference]:
        """The user's preference for each site id they have set one for."""
        rows = self.session.scalars(select(SitePreference).where(SitePreference.user_id == user_id))
        return {pref.site_id: pref for pref in rows}

    def add_preference(self, preference: SitePreference) -> SitePreference:
        self.session.add(preference)
        self.session.flush()
        return preference


class ReminderRepository(Repository[Reminder]):
    model = Reminder

    def active_for(self, user_id: int) -> Sequence[Reminder]:
        return self.session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user_id, Reminder.active.is_(True))
            .order_by(Reminder.id)
        ).all()


class FavouriteRepository(Repository[FavouriteMeal]):
    model = FavouriteMeal

    def for_user(self, user_id: int) -> Sequence[FavouriteMeal]:
        """The user's favourites, sorted by name ignoring case."""
        return self.session.scalars(
            select(FavouriteMeal)
            .where(FavouriteMeal.user_id == user_id)
            .order_by(func.lower(FavouriteMeal.name), FavouriteMeal.id)
        ).all()

    def get_owned(self, user_id: int, favourite_id: int) -> FavouriteMeal | None:
        return self.session.scalars(
            select(FavouriteMeal).where(
                FavouriteMeal.id == favourite_id, FavouriteMeal.user_id == user_id
            )
        ).one_or_none()

    def find_by_name(self, user_id: int, name: str) -> FavouriteMeal | None:
        """The user's favourite with this name, ignoring case."""
        return self.session.scalars(
            select(FavouriteMeal).where(
                FavouriteMeal.user_id == user_id, func.lower(FavouriteMeal.name) == name.lower()
            )
        ).first()

    def count(self, user_id: int) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(FavouriteMeal)
                .where(FavouriteMeal.user_id == user_id)
            )
            or 0
        )

    def delete(self, favourite: FavouriteMeal) -> None:
        self.session.delete(favourite)
        self.session.flush()


class HypoRepository(Repository[HypoTreatment]):
    model = HypoTreatment

    def between(self, user_id: int, start: datetime, end: datetime) -> Sequence[HypoTreatment]:
        _check_range(start, end)
        return self.session.scalars(
            select(HypoTreatment)
            .where(
                HypoTreatment.user_id == user_id,
                HypoTreatment.treated_at >= start,
                HypoTreatment.treated_at < end,
            )
            .order_by(HypoTreatment.treated_at)
        ).all()

    def recent(self, user_id: int, limit: int) -> Sequence[HypoTreatment]:
        return self.session.scalars(
            select(HypoTreatment)
            .where(HypoTreatment.user_id == user_id)
            .order_by(HypoTreatment.treated_at.desc(), HypoTreatment.id.desc())
            .limit(limit)
        ).all()
