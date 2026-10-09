"""Reminders: defaults per mode, done and snooze, quiet hours, firing and the hypo recheck."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.models import (
    DeliveryMode,
    DoseKind,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    Reminder,
    ReminderKind,
    RuleType,
    User,
    UserSettings,
)
from glucobalance.reminder_service import (
    ReminderError,
    ReminderInput,
    create_reminder,
    delete_reminder,
    ensure_default_reminders,
    fire_due_reminders,
    list_notifications,
    list_reminders,
    mark_all_read,
    mark_done,
    mark_read,
    schedule_hypo_recheck,
    set_active,
    set_quiet_hours,
    snooze,
    unread_count,
)

WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)  # 12:00 in Warsaw


def make_user(
    session: Session,
    delivery: DeliveryMode = DeliveryMode.PUMP,
    monitoring: MonitoringMode = MonitoringMode.GLUCOMETER,
    email: str = "ann@example.com",
) -> User:
    user = register(session, email, "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=delivery,
            monitoring_mode=monitoring,
            max_bolus_units=Decimal("10"),
            timezone="Europe/Warsaw",
            set_change_days=3,
        )
    )
    session.flush()
    return user


@pytest.fixture
def user(session: Session) -> User:
    return make_user(session)


def kinds(reminders: list[Reminder]) -> set[ReminderKind]:
    return {r.kind for r in reminders}


def one(session: Session, user: User, kind: ReminderKind) -> Reminder:
    (reminder,) = [r for r in list_reminders(session, user) if r.kind is kind]
    return reminder


# ---------- defaults ----------


def test_pump_with_meter_gets_set_reservoir_check_and_recheck(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    assert kinds(list(list_reminders(session, user))) == {
        ReminderKind.SET_CHANGE,
        ReminderKind.RESERVOIR,
        ReminderKind.GLUCOSE_CHECK,
        ReminderKind.HYPO_RECHECK,
    }


def test_pens_with_cgm_get_long_acting_missed_dose_expiry_and_sensor(session: Session) -> None:
    user = make_user(session, DeliveryMode.PENS, MonitoringMode.CGM)
    ensure_default_reminders(session, user, now=NOW)
    assert kinds(list(list_reminders(session, user))) == {
        ReminderKind.LONG_ACTING_DOSE,
        ReminderKind.MISSED_DOSE,
        ReminderKind.PEN_EXPIRY,
        ReminderKind.SENSOR_CHANGE,
    }


def test_defaults_are_created_once(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    again = ensure_default_reminders(session, user, now=NOW)
    assert again == []
    assert len(list_reminders(session, user)) == 4


def test_the_set_change_reminder_follows_the_set_change_days_setting(
    session: Session, user: User
) -> None:
    assert user.settings is not None
    user.settings.set_change_days = 2
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    assert reminder.interval_days == 2
    assert reminder.next_due_at == NOW + timedelta(days=2)


def test_the_daily_check_is_due_at_its_next_local_time(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    assert reminder.rule_type is RuleType.DAILY_AT
    assert reminder.next_due_at is not None
    assert reminder.next_due_at.astimezone(WARSAW).time() == reminder.time_of_day


# ---------- creating ----------


def test_create_a_custom_every_n_days_reminder(session: Session, user: User) -> None:
    reminder = create_reminder(
        session,
        user,
        ReminderInput(
            kind=ReminderKind.CUSTOM,
            title="Order supplies",
            rule_type=RuleType.EVERY_N_DAYS,
            interval_days=10,
        ),
        now=NOW,
    )
    assert reminder.next_due_at == NOW + timedelta(days=10)
    assert reminder.active


@pytest.mark.parametrize(
    "data",
    [
        ReminderInput(ReminderKind.CUSTOM, "", RuleType.EVERY_N_DAYS, interval_days=3),
        ReminderInput(ReminderKind.CUSTOM, "x" * 101, RuleType.EVERY_N_DAYS, interval_days=3),
        ReminderInput(ReminderKind.CUSTOM, "No interval", RuleType.EVERY_N_DAYS),
        ReminderInput(ReminderKind.CUSTOM, "Zero", RuleType.EVERY_N_DAYS, interval_days=0),
        ReminderInput(ReminderKind.CUSTOM, "Too long", RuleType.EVERY_N_DAYS, interval_days=400),
        ReminderInput(ReminderKind.CUSTOM, "No time", RuleType.DAILY_AT),
        ReminderInput(ReminderKind.CUSTOM, "No delay", RuleType.AFTER_EVENT),
        ReminderInput(ReminderKind.CUSTOM, "Negative", RuleType.AFTER_EVENT, delay_minutes=-5),
    ],
)
def test_invalid_reminders_are_rejected(session: Session, user: User, data: ReminderInput) -> None:
    with pytest.raises(ReminderError):
        create_reminder(session, user, data, now=NOW)


# ---------- done, snooze, switch off ----------


def test_done_restarts_an_every_n_days_reminder_from_now(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    later = NOW + timedelta(days=4)
    mark_done(session, user, reminder.id, now=later)
    assert reminder.last_done_at == later
    assert reminder.next_due_at == later + timedelta(days=3)


def test_done_on_a_daily_reminder_waits_for_the_next_day(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    first = reminder.next_due_at
    assert first is not None
    mark_done(session, user, reminder.id, now=first + timedelta(minutes=5))
    assert reminder.next_due_at == first + timedelta(days=1)


def test_done_before_the_time_skips_todays_reminder(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    first = reminder.next_due_at
    assert first is not None
    mark_done(session, user, reminder.id, now=first - timedelta(hours=1))
    assert reminder.next_due_at == first + timedelta(days=1)


def test_done_clears_a_snooze_and_an_after_event_reminder_waits_for_its_event(
    session: Session, user: User
) -> None:
    ensure_default_reminders(session, user, now=NOW)
    recheck = one(session, user, ReminderKind.HYPO_RECHECK)
    schedule_hypo_recheck(session, user, event_at=NOW, now=NOW)
    snooze(session, user, recheck.id, minutes=10, now=NOW)
    mark_done(session, user, recheck.id, now=NOW + timedelta(minutes=16))
    assert recheck.snoozed_until is None
    assert recheck.next_due_at is None


def test_snooze_sets_a_time_in_the_future(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    snooze(session, user, reminder.id, minutes=30, now=NOW)
    assert reminder.snoozed_until == NOW + timedelta(minutes=30)


@pytest.mark.parametrize("minutes", [0, -5, 24 * 60 + 1])
def test_snooze_rejects_silly_lengths(session: Session, user: User, minutes: int) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    with pytest.raises(ReminderError):
        snooze(session, user, reminder.id, minutes=minutes, now=NOW)


def test_switching_a_reminder_off_and_on_again_recomputes_when_it_is_due(
    session: Session, user: User
) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    set_active(session, user, reminder.id, False, now=NOW)
    assert not reminder.active
    later = NOW + timedelta(days=10)
    set_active(session, user, reminder.id, True, now=later)
    assert reminder.active
    assert reminder.next_due_at == later + timedelta(days=3)


def test_one_user_cannot_touch_anothers_reminder(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    other = make_user(session, email="bob@example.com")
    with pytest.raises(ReminderError):
        mark_done(session, other, reminder.id, now=NOW)
    with pytest.raises(ReminderError):
        delete_reminder(session, other, reminder.id)


def test_delete_removes_a_reminder(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    delete_reminder(session, user, reminder.id)
    assert ReminderKind.SET_CHANGE not in kinds(list(list_reminders(session, user)))


# ---------- firing ----------


def test_a_reminder_that_is_not_due_does_not_fire(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    assert fire_due_reminders(session, now=NOW + timedelta(hours=1)) == []


def test_a_due_reminder_creates_one_notification(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    due = NOW + timedelta(days=3, minutes=1)
    # Keep the clock in the afternoon so quiet hours do not interfere.
    due = due.replace(hour=13)
    fired = fire_due_reminders(session, now=due)
    assert [n.reminder_id for n in fired if n.reminder_id == reminder.id] == [reminder.id]
    assert unread_count(session, user) >= 1


def test_firing_twice_does_not_notify_twice(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    due = (NOW + timedelta(days=3)).replace(hour=13)
    fire_due_reminders(session, now=due)
    again = fire_due_reminders(session, now=due + timedelta(minutes=1))
    assert [n for n in again if n.reminder_id == reminder.id] == []


def test_an_unanswered_every_n_days_reminder_repeats_the_next_day(
    session: Session, user: User
) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.SET_CHANGE)
    due = (NOW + timedelta(days=3)).replace(hour=13)
    fire_due_reminders(session, now=due)
    assert reminder.next_due_at is not None
    assert reminder.next_due_at > due
    assert reminder.next_due_at <= due + timedelta(days=1, minutes=1)


def test_a_daily_reminder_fires_and_is_set_for_tomorrow(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    first = reminder.next_due_at
    assert first is not None
    fire_due_reminders(session, now=first)
    assert reminder.next_due_at == first + timedelta(days=1)


def test_a_snoozed_reminder_stays_quiet_until_the_snooze_ends(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    first = reminder.next_due_at
    assert first is not None
    snooze(session, user, reminder.id, minutes=30, now=first)
    during = fire_due_reminders(session, now=first + timedelta(minutes=10))
    assert [n for n in during if n.reminder_id == reminder.id] == []
    after = fire_due_reminders(session, now=first + timedelta(minutes=31))
    assert [n.reminder_id for n in after if n.reminder_id == reminder.id] == [reminder.id]


def test_an_inactive_reminder_never_fires(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = one(session, user, ReminderKind.GLUCOSE_CHECK)
    first = reminder.next_due_at
    assert first is not None
    set_active(session, user, reminder.id, False, now=NOW)
    assert [n for n in fire_due_reminders(session, now=first) if n.reminder_id == reminder.id] == []


# ---------- quiet hours ----------


def test_quiet_hours_hold_a_reminder_until_they_end(session: Session, user: User) -> None:
    set_quiet_hours(session, user, time(22, 0), time(7, 0))
    reminder = create_reminder(
        session,
        user,
        ReminderInput(ReminderKind.CUSTOM, "Midnight", RuleType.DAILY_AT, time_of_day=time(23, 30)),
        now=NOW,
    )
    due = reminder.next_due_at
    assert due is not None
    assert [n for n in fire_due_reminders(session, now=due) if n.reminder_id == reminder.id] == []
    morning = datetime(2026, 10, 10, 7, 0, tzinfo=WARSAW)
    fired = fire_due_reminders(session, now=morning)
    assert [n.reminder_id for n in fired if n.reminder_id == reminder.id] == [reminder.id]


def test_the_hypo_recheck_ignores_quiet_hours(session: Session, user: User) -> None:
    set_quiet_hours(session, user, time(22, 0), time(7, 0))
    ensure_default_reminders(session, user, now=NOW)
    night = datetime(2026, 10, 9, 23, 30, tzinfo=WARSAW)
    schedule_hypo_recheck(session, user, event_at=night, now=night)
    recheck = one(session, user, ReminderKind.HYPO_RECHECK)
    fired = fire_due_reminders(session, now=night + timedelta(minutes=15))
    assert [n.reminder_id for n in fired if n.reminder_id == recheck.id] == [recheck.id]


def test_quiet_hours_must_be_set_as_a_pair(session: Session, user: User) -> None:
    with pytest.raises(ReminderError):
        set_quiet_hours(session, user, time(22, 0), None)
    set_quiet_hours(session, user, None, None)
    assert user.settings is not None
    assert user.settings.quiet_start is None


# ---------- hypo recheck ----------


def test_a_low_reading_schedules_a_recheck_15_minutes_later(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    reminder = schedule_hypo_recheck(session, user, event_at=NOW, now=NOW)
    assert reminder is not None
    assert reminder.next_due_at == NOW + timedelta(minutes=15)


def test_a_new_low_restarts_the_recheck_clock(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    schedule_hypo_recheck(session, user, event_at=NOW, now=NOW)
    later = NOW + timedelta(minutes=10)
    reminder = schedule_hypo_recheck(session, user, event_at=later, now=later)
    assert reminder is not None
    assert reminder.next_due_at == later + timedelta(minutes=15)


def test_cgm_users_get_no_hypo_recheck(session: Session) -> None:
    user = make_user(session, DeliveryMode.PUMP, MonitoringMode.CGM)
    assert schedule_hypo_recheck(session, user, event_at=NOW, now=NOW) is None


def test_the_recheck_is_created_on_demand_for_meter_users(session: Session, user: User) -> None:
    reminder = schedule_hypo_recheck(session, user, event_at=NOW, now=NOW)
    assert reminder is not None
    assert reminder.kind is ReminderKind.HYPO_RECHECK


# ---------- missed long-acting dose ----------


def pens_user(session: Session) -> User:
    return make_user(session, DeliveryMode.PENS, MonitoringMode.GLUCOMETER)


def test_the_long_acting_reminder_arms_the_missed_dose_check(session: Session) -> None:
    user = pens_user(session)
    ensure_default_reminders(session, user, now=NOW)
    long_acting = one(session, user, ReminderKind.LONG_ACTING_DOSE)
    due = long_acting.next_due_at
    assert due is not None
    fire_due_reminders(session, now=due)
    assert one(session, user, ReminderKind.MISSED_DOSE).next_due_at == due + timedelta(hours=2)


def test_a_missed_dose_alert_fires_when_no_long_acting_dose_was_logged(session: Session) -> None:
    user = pens_user(session)
    ensure_default_reminders(session, user, now=NOW)
    due = one(session, user, ReminderKind.LONG_ACTING_DOSE).next_due_at
    assert due is not None
    fire_due_reminders(session, now=due)
    missed = one(session, user, ReminderKind.MISSED_DOSE)
    fired = fire_due_reminders(session, now=due + timedelta(hours=2))
    assert [n.reminder_id for n in fired if n.reminder_id == missed.id] == [missed.id]


def test_no_missed_dose_alert_when_the_dose_was_logged(session: Session) -> None:
    user = pens_user(session)
    ensure_default_reminders(session, user, now=NOW)
    due = one(session, user, ReminderKind.LONG_ACTING_DOSE).next_due_at
    assert due is not None
    fire_due_reminders(session, now=due)
    session.add(
        InsulinDose(
            user_id=user.id,
            taken_at=due + timedelta(minutes=30),
            units=Decimal("20"),
            insulin_type=InsulinType.LONG,
            kind=DoseKind.BASAL,
        )
    )
    session.flush()
    missed = one(session, user, ReminderKind.MISSED_DOSE)
    fired = fire_due_reminders(session, now=due + timedelta(hours=2))
    assert [n for n in fired if n.reminder_id == missed.id] == []
    assert missed.next_due_at is None


def test_marking_the_long_acting_dose_done_cancels_the_missed_dose_check(session: Session) -> None:
    user = pens_user(session)
    ensure_default_reminders(session, user, now=NOW)
    long_acting = one(session, user, ReminderKind.LONG_ACTING_DOSE)
    due = long_acting.next_due_at
    assert due is not None
    fire_due_reminders(session, now=due)
    mark_done(session, user, long_acting.id, now=due + timedelta(minutes=10))
    assert one(session, user, ReminderKind.MISSED_DOSE).next_due_at is None


# ---------- notification centre ----------


def test_notifications_are_listed_newest_first_and_can_be_read(
    session: Session, user: User
) -> None:
    ensure_default_reminders(session, user, now=NOW)
    first = one(session, user, ReminderKind.GLUCOSE_CHECK).next_due_at
    assert first is not None
    fire_due_reminders(session, now=first)
    fire_due_reminders(session, now=first + timedelta(days=1))
    notes = list_notifications(session, user)
    assert len(notes) == 2
    assert notes[0].created_at > notes[1].created_at
    assert unread_count(session, user) == 2
    mark_read(session, user, notes[0].id, now=NOW)
    assert unread_count(session, user) == 1
    mark_all_read(session, user, now=NOW)
    assert unread_count(session, user) == 0


def test_another_users_notification_cannot_be_marked_read(session: Session, user: User) -> None:
    ensure_default_reminders(session, user, now=NOW)
    first = one(session, user, ReminderKind.GLUCOSE_CHECK).next_due_at
    assert first is not None
    fire_due_reminders(session, now=first)
    (note,) = list_notifications(session, user)
    other = make_user(session, email="bob@example.com")
    with pytest.raises(ReminderError):
        mark_read(session, other, note.id, now=NOW)
