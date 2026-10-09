"""Reminders: the default set for each mode, done, snooze, quiet hours and firing.

``reminder_rules`` does the date maths; this module keeps the rows. Every function takes
``now`` so tests control the clock, flushes through repositories and never commits.

``fire_due_reminders`` is what the scheduler runs every minute: it turns each reminder whose
time has come into a ``Notification`` (the in-app notification centre). Sending the push
message for those notifications is a separate step (``push``), so a push failure can never
lose a notification.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.entries import EntryError
from glucobalance.features import FeatureFlags, feature_flags
from glucobalance.hypo_service import RECHECK_MINUTES
from glucobalance.models import (
    Notification,
    Reminder,
    ReminderKind,
    RuleType,
    User,
    UserSettings,
)
from glucobalance.models.insulin import InsulinType
from glucobalance.reminder_rules import (
    QuietHours,
    after_event,
    apply_quiet_hours,
    apply_snooze,
    next_daily,
    next_every_n_days,
)
from glucobalance.repositories import (
    InsulinRepository,
    NotificationRepository,
    ReminderRepository,
)

TITLE_MAX_LENGTH = 100
MAX_INTERVAL_DAYS = 365
MAX_DELAY_MINUTES = 7 * 24 * 60
MAX_SNOOZE_MINUTES = 24 * 60
NOTIFICATION_LIMIT = 50

# Reminders about a low are never held back by quiet hours.
URGENT_KINDS = frozenset({ReminderKind.HYPO_RECHECK})
# If the long-acting dose is still not logged this long after its reminder, say so.
MISSED_DOSE_DELAY_MINUTES = 120
# A dose taken up to this long before the reminder fired still counts as taken.
EARLY_DOSE_GRACE = timedelta(hours=1)

MESSAGES = {
    ReminderKind.SET_CHANGE: "Time to change your infusion set.",
    ReminderKind.RESERVOIR: "Check or change your pump reservoir.",
    ReminderKind.LONG_ACTING_DOSE: "Time for your long-acting insulin.",
    ReminderKind.MISSED_DOSE: "No long-acting dose is logged yet. Did you take it?",
    ReminderKind.PEN_NEEDLE: "Check that you have pen needles.",
    ReminderKind.PEN_EXPIRY: "Check the expiry date on your pens.",
    ReminderKind.GLUCOSE_CHECK: "Time to check your glucose.",
    ReminderKind.SENSOR_CHANGE: "Time to change your CGM sensor.",
    ReminderKind.HYPO_RECHECK: "Recheck your glucose after the low.",
}


class ReminderError(EntryError):
    """The reminder or the request is not acceptable. The message can be shown to the user."""


@dataclass(frozen=True, slots=True)
class ReminderInput:
    kind: ReminderKind
    title: str
    rule_type: RuleType
    interval_days: int | None = None
    time_of_day: time | None = None
    delay_minutes: int | None = None


# ---------- small helpers ----------


def _settings(user: User) -> UserSettings:
    if user.settings is None:
        raise ReminderError("Finish the setup first.")
    return user.settings


def _zone(settings: UserSettings) -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def quiet_hours_for(settings: UserSettings) -> QuietHours | None:
    if settings.quiet_start is None or settings.quiet_end is None:
        return None
    return QuietHours(settings.quiet_start, settings.quiet_end)


def _owned(session: Session, user: User, reminder_id: int) -> Reminder:
    reminder = ReminderRepository(session).get_owned(user.id, reminder_id)
    if reminder is None:
        raise ReminderError("That reminder does not exist.")
    return reminder


def _validate(data: ReminderInput) -> str:
    title = data.title.strip()
    if not title:
        raise ReminderError("Give the reminder a name.")
    if len(title) > TITLE_MAX_LENGTH:
        raise ReminderError(f"Keep the name under {TITLE_MAX_LENGTH} characters.")
    match data.rule_type:
        case RuleType.EVERY_N_DAYS:
            if data.interval_days is None or not 1 <= data.interval_days <= MAX_INTERVAL_DAYS:
                raise ReminderError(f"Choose between 1 and {MAX_INTERVAL_DAYS} days.")
        case RuleType.DAILY_AT:
            if data.time_of_day is None:
                raise ReminderError("Choose the time of day.")
        case RuleType.AFTER_EVENT:
            if data.delay_minutes is None or not 0 <= data.delay_minutes <= MAX_DELAY_MINUTES:
                raise ReminderError("Choose a delay of 0 minutes or more.")
    return title


def _first_due(reminder: Reminder, zone: ZoneInfo, now: datetime) -> datetime | None:
    """When a new or re-enabled reminder is first due."""
    match reminder.rule_type:
        case RuleType.EVERY_N_DAYS:
            assert reminder.interval_days is not None
            return next_every_n_days(now, reminder.interval_days, zone, time_of_day=None)
        case RuleType.DAILY_AT:
            assert reminder.time_of_day is not None
            return next_daily(now, reminder.time_of_day, zone)
        case RuleType.AFTER_EVENT:
            return None


# ---------- creating and defaults ----------


def create_reminder(
    session: Session, user: User, data: ReminderInput, *, now: datetime
) -> Reminder:
    title = _validate(data)
    zone = _zone(_settings(user))
    reminder = Reminder(
        user_id=user.id,
        kind=data.kind,
        title=title,
        rule_type=data.rule_type,
        interval_days=data.interval_days if data.rule_type is RuleType.EVERY_N_DAYS else None,
        time_of_day=data.time_of_day if data.rule_type is RuleType.DAILY_AT else None,
        delay_minutes=data.delay_minutes if data.rule_type is RuleType.AFTER_EVENT else None,
        active=True,
    )
    reminder.next_due_at = _first_due(reminder, zone, now)
    return ReminderRepository(session).add(reminder)


def default_reminders(flags: FeatureFlags, settings: UserSettings) -> list[ReminderInput]:
    """The reminders each mode starts with. Every one can be edited or switched off."""
    every, daily, event = RuleType.EVERY_N_DAYS, RuleType.DAILY_AT, RuleType.AFTER_EVENT
    wanted: list[ReminderInput] = []
    if flags.infusion_set_reminder:
        wanted.append(
            ReminderInput(
                ReminderKind.SET_CHANGE,
                "Change infusion set",
                every,
                interval_days=settings.set_change_days,
            )
        )
    if flags.reservoir_reminder:
        wanted.append(
            ReminderInput(ReminderKind.RESERVOIR, "Check pump reservoir", every, interval_days=3)
        )
    if flags.long_acting_dose_reminder:
        wanted.append(
            ReminderInput(
                ReminderKind.LONG_ACTING_DOSE,
                "Long-acting insulin",
                daily,
                time_of_day=time(21, 0),
            )
        )
    if flags.missed_dose_alert:
        wanted.append(
            ReminderInput(
                ReminderKind.MISSED_DOSE,
                "Missed long-acting dose",
                event,
                delay_minutes=MISSED_DOSE_DELAY_MINUTES,
            )
        )
    if flags.pen_expiry_reminder:
        wanted.append(
            ReminderInput(ReminderKind.PEN_EXPIRY, "Check pen expiry", every, interval_days=28)
        )
    if flags.glucose_check_reminders:
        wanted.append(
            ReminderInput(
                ReminderKind.GLUCOSE_CHECK, "Check glucose", daily, time_of_day=time(7, 30)
            )
        )
    if flags.recheck_reminder_after_out_of_range:
        wanted.append(
            ReminderInput(
                ReminderKind.HYPO_RECHECK,
                "Recheck after a low",
                event,
                delay_minutes=RECHECK_MINUTES,
            )
        )
    if flags.sensor_change_reminder:
        wanted.append(
            ReminderInput(ReminderKind.SENSOR_CHANGE, "Change CGM sensor", every, interval_days=14)
        )
    return wanted


def ensure_default_reminders(session: Session, user: User, *, now: datetime) -> list[Reminder]:
    """Create the default reminders the user does not have yet. Safe to call repeatedly."""
    settings = _settings(user)
    flags = feature_flags(settings.delivery_mode, settings.monitoring_mode)
    existing = {r.kind for r in ReminderRepository(session).for_user(user.id)}
    return [
        create_reminder(session, user, data, now=now)
        for data in default_reminders(flags, settings)
        if data.kind not in existing
    ]


def list_reminders(session: Session, user: User) -> Sequence[Reminder]:
    return ReminderRepository(session).for_user(user.id)


# ---------- done, snooze, on and off ----------


def mark_done(session: Session, user: User, reminder_id: int, *, now: datetime) -> Reminder:
    reminder = _owned(session, user, reminder_id)
    zone = _zone(_settings(user))
    reminder.last_done_at = now
    reminder.snoozed_until = None
    match reminder.rule_type:
        case RuleType.EVERY_N_DAYS:
            assert reminder.interval_days is not None
            reminder.next_due_at = next_every_n_days(
                now, reminder.interval_days, zone, time_of_day=reminder.time_of_day
            )
        case RuleType.DAILY_AT:
            assert reminder.time_of_day is not None
            # Done ahead of time: skip today's reminder as well.
            after = (
                reminder.next_due_at if reminder.next_due_at and reminder.next_due_at > now else now
            )
            reminder.next_due_at = next_daily(after, reminder.time_of_day, zone)
        case RuleType.AFTER_EVENT:
            reminder.next_due_at = None
    if reminder.kind is ReminderKind.LONG_ACTING_DOSE:
        _cancel(session, user, ReminderKind.MISSED_DOSE)
    session.flush()
    return reminder


def _cancel(session: Session, user: User, kind: ReminderKind) -> None:
    follow_up = ReminderRepository(session).of_kind(user.id, kind)
    if follow_up is not None:
        follow_up.next_due_at = None
        follow_up.snoozed_until = None


def snooze(
    session: Session, user: User, reminder_id: int, *, minutes: int, now: datetime
) -> Reminder:
    if not 1 <= minutes <= MAX_SNOOZE_MINUTES:
        raise ReminderError("Snooze for between 1 minute and 24 hours.")
    reminder = _owned(session, user, reminder_id)
    reminder.snoozed_until = now + timedelta(minutes=minutes)
    session.flush()
    return reminder


def set_active(
    session: Session, user: User, reminder_id: int, active: bool, *, now: datetime
) -> Reminder:
    reminder = _owned(session, user, reminder_id)
    if active and not reminder.active:
        reminder.next_due_at = _first_due(reminder, _zone(_settings(user)), now)
        reminder.snoozed_until = None
    reminder.active = active
    session.flush()
    return reminder


def delete_reminder(session: Session, user: User, reminder_id: int) -> None:
    ReminderRepository(session).delete(_owned(session, user, reminder_id))


def set_quiet_hours(
    session: Session, user: User, start: time | None, end: time | None
) -> UserSettings:
    """Set both ends or neither."""
    if (start is None) != (end is None):
        raise ReminderError("Set both the start and the end of quiet hours, or neither.")
    settings = _settings(user)
    settings.quiet_start = start
    settings.quiet_end = end
    session.flush()
    return settings


# ---------- hypo recheck ----------


def schedule_hypo_recheck(
    session: Session, user: User, *, event_at: datetime, now: datetime
) -> Reminder | None:
    """Ask for a recheck ``RECHECK_MINUTES`` after a low (or its treatment).

    Only for users who measure with a meter; CGM users see their own trend. A newer low
    restarts the clock. Returns ``None`` when the mode has no recheck reminder.
    """
    settings = _settings(user)
    flags = feature_flags(settings.delivery_mode, settings.monitoring_mode)
    if not flags.recheck_reminder_after_out_of_range:
        return None
    ensure_default_reminders(session, user, now=now)
    reminder = ReminderRepository(session).of_kind(user.id, ReminderKind.HYPO_RECHECK)
    assert reminder is not None
    if not reminder.active:
        return reminder
    reminder.next_due_at = after_event(event_at, reminder.delay_minutes or RECHECK_MINUTES)
    reminder.snoozed_until = None
    session.flush()
    return reminder


# ---------- firing ----------


def _effective_due(reminder: Reminder, settings: UserSettings) -> datetime:
    assert reminder.next_due_at is not None
    due = apply_snooze(reminder.next_due_at, reminder.snoozed_until)
    return apply_quiet_hours(
        due, quiet_hours_for(settings), _zone(settings), urgent=reminder.kind in URGENT_KINDS
    )


def _after_firing(session: Session, reminder: Reminder, zone: ZoneInfo, now: datetime) -> None:
    """Set the next due time once a reminder has fired."""
    due = reminder.next_due_at
    assert due is not None
    reminder.snoozed_until = None
    match reminder.rule_type:
        case RuleType.DAILY_AT:
            assert reminder.time_of_day is not None
            reminder.next_due_at = next_daily(now, reminder.time_of_day, zone)
        case RuleType.EVERY_N_DAYS:
            # Keep asking once a day, at the same time, until the user marks it done.
            reminder.next_due_at = next_daily(now, due.astimezone(zone).time(), zone)
        case RuleType.AFTER_EVENT:
            reminder.next_due_at = None
    if reminder.kind is ReminderKind.LONG_ACTING_DOSE:
        _arm_missed_dose(session, reminder.user_id, now)


def _arm_missed_dose(session: Session, user_id: int, now: datetime) -> None:
    missed = ReminderRepository(session).of_kind(user_id, ReminderKind.MISSED_DOSE)
    if missed is not None and missed.active:
        missed.next_due_at = after_event(now, missed.delay_minutes or MISSED_DOSE_DELAY_MINUTES)
        missed.snoozed_until = None


def _long_acting_taken(session: Session, reminder: Reminder) -> bool:
    """Was a long-acting dose logged since this missed-dose check was armed?"""
    assert reminder.next_due_at is not None
    delay = timedelta(minutes=reminder.delay_minutes or MISSED_DOSE_DELAY_MINUTES)
    start = reminder.next_due_at - delay - EARLY_DOSE_GRACE
    doses = InsulinRepository(session).between(
        reminder.user_id, start, reminder.next_due_at + timedelta(microseconds=1)
    )
    return any(d.insulin_type is InsulinType.LONG for d in doses)


def fire_due_reminders(session: Session, *, now: datetime) -> list[Notification]:
    """Create a notification for every reminder that is due, and set its next due time.

    Snooze and quiet hours are applied here: a reminder that has been moved later simply
    stays untouched until its effective time arrives.
    """
    created: list[Notification] = []
    notifications = NotificationRepository(session)
    for reminder in ReminderRepository(session).due(now):
        settings = reminder.user.settings
        if settings is None or _effective_due(reminder, settings) > now:
            continue
        if reminder.kind is ReminderKind.MISSED_DOSE and _long_acting_taken(session, reminder):
            reminder.next_due_at = None
            continue
        created.append(
            notifications.add(
                Notification(
                    user_id=reminder.user_id,
                    reminder_id=reminder.id,
                    title=reminder.title,
                    body=MESSAGES.get(reminder.kind),
                    created_at=now,
                )
            )
        )
        _after_firing(session, reminder, _zone(settings), now)
    session.flush()
    return created


# ---------- notification centre ----------


def list_notifications(session: Session, user: User) -> Sequence[Notification]:
    return NotificationRepository(session).recent(user.id, NOTIFICATION_LIMIT)


def unread_count(session: Session, user: User) -> int:
    return NotificationRepository(session).unread_count(user.id)


def mark_read(session: Session, user: User, notification_id: int, *, now: datetime) -> None:
    notification = NotificationRepository(session).get_owned(user.id, notification_id)
    if notification is None:
        raise ReminderError("That notification does not exist.")
    if notification.read_at is None:
        notification.read_at = now
        session.flush()


def mark_all_read(session: Session, user: User, *, now: datetime) -> None:
    for notification in NotificationRepository(session).unread(user.id):
        notification.read_at = now
    session.flush()
