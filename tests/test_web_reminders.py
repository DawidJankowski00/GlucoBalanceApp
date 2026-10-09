"""The /reminders and /notifications pages, and the hooks that create reminders."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.db import make_session_factory
from glucobalance.models import Notification, Reminder, ReminderKind
from glucobalance.reminder_service import fire_due_reminders
from test_web import STEP1, onboard, saved_user, sign_up
from test_web_glucose import local


def pump(client: TestClient) -> None:
    sign_up(client)
    onboard(client)


def pump_with_meter(client: TestClient) -> None:
    sign_up(client)
    onboard(client, {**STEP1, "monitoring_mode": "glucometer", "timezone": "Europe/Warsaw"})


def reminder_of(engine: Engine, kind: ReminderKind) -> Reminder:
    session, _ = saved_user(engine)
    reminder = session.query(Reminder).filter_by(kind=kind).one()
    session.close()
    return reminder


def test_pages_need_login(client: TestClient) -> None:
    for path in ("/reminders", "/notifications"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_finishing_onboarding_creates_the_default_reminders(client: TestClient) -> None:
    pump(client)
    page = client.get("/reminders").text
    assert "Change infusion set" in page
    assert "Check pump reservoir" in page
    assert "Change CGM sensor" in page  # STEP1 uses a CGM
    assert "Check glucose" not in page
    assert "Long-acting insulin" not in page


def test_pens_get_the_pen_reminders(client: TestClient) -> None:
    sign_up(client)
    onboard(client, {**STEP1, "delivery_mode": "pens"})
    page = client.get("/reminders").text
    assert "Long-acting insulin" in page
    assert "Check pen expiry" in page
    assert "Change infusion set" not in page


def test_add_and_delete_a_custom_reminder(client: TestClient, engine: Engine) -> None:
    pump(client)
    response = client.post(
        "/reminders",
        data={"title": "Order supplies", "rule_type": "every_n_days", "interval_days": "30"},
    )
    assert response.status_code == 200
    assert "Order supplies" in response.text
    session, _ = saved_user(engine)
    custom = session.query(Reminder).filter_by(kind=ReminderKind.CUSTOM).one()
    session.close()

    response = client.post(f"/reminders/{custom.id}/delete")
    assert "Order supplies" not in response.text


def test_a_bad_custom_reminder_shows_the_error(client: TestClient) -> None:
    pump(client)
    response = client.post(
        "/reminders", data={"title": "x", "rule_type": "every_n_days", "interval_days": "abc"}
    )
    assert response.status_code == 422
    assert "Enter the days as a number" in response.text


def test_done_snooze_and_off(client: TestClient, engine: Engine) -> None:
    pump(client)
    set_change = reminder_of(engine, ReminderKind.SET_CHANGE)

    assert "Marked as done" in client.post(f"/reminders/{set_change.id}/done").text
    snoozed = client.post(f"/reminders/{set_change.id}/snooze", data={"minutes": "60"})
    assert "Snoozed until" in snoozed.text
    assert (
        client.post(f"/reminders/{set_change.id}/snooze", data={"minutes": "0"}).status_code == 422
    )
    assert "Switch on" in client.post(f"/reminders/{set_change.id}/off").text
    assert "Switch off" in client.post(f"/reminders/{set_change.id}/on").text


def test_one_user_cannot_change_anothers_reminder(client: TestClient, engine: Engine) -> None:
    pump(client)
    set_change = reminder_of(engine, ReminderKind.SET_CHANGE)
    client.post("/logout")
    sign_up(client, "bob@example.com")
    onboard(client)
    response = client.post(f"/reminders/{set_change.id}/delete")
    assert response.status_code == 422


def test_quiet_hours_are_saved_and_shown(client: TestClient) -> None:
    pump(client)
    page = client.post(
        "/reminders/quiet-hours", data={"quiet_start": "22:00", "quiet_end": "07:00"}
    )
    assert 'value="22:00"' in page.text
    assert 'value="07:00"' in page.text
    bad = client.post("/reminders/quiet-hours", data={"quiet_start": "22:00", "quiet_end": ""})
    assert bad.status_code == 422


def test_a_due_reminder_shows_in_the_notification_centre(
    client: TestClient, engine: Engine
) -> None:
    pump(client)
    assert "Nothing yet" in client.get("/notifications").text
    session = make_session_factory(engine)()
    fire_due_reminders(session, now=datetime.now(UTC) + timedelta(days=10))
    session.commit()
    session.close()

    page = client.get("/notifications").text
    assert "Change infusion set" in page
    assert "Alerts" in page
    assert "new reminder" in client.get("/").text

    client.post("/notifications/read-all")
    assert "new reminder" not in client.get("/").text


def test_a_low_reading_schedules_the_recheck(client: TestClient, engine: Engine) -> None:
    pump_with_meter(client)
    client.post("/log/glucose", data={"value": "55", "measured_at": local()})
    recheck = reminder_of(engine, ReminderKind.HYPO_RECHECK)
    assert recheck.next_due_at is not None


def test_a_normal_reading_does_not_arm_the_recheck(client: TestClient, engine: Engine) -> None:
    pump_with_meter(client)
    client.post("/log/glucose", data={"value": "120", "measured_at": local()})
    assert reminder_of(engine, ReminderKind.HYPO_RECHECK).next_due_at is None


def test_notifications_table_starts_empty(client: TestClient, engine: Engine) -> None:
    pump(client)
    session, _ = saved_user(engine)
    assert session.query(Notification).count() == 0
    session.close()


def test_treating_a_low_restarts_the_recheck_from_the_treatment_time(
    client: TestClient, engine: Engine
) -> None:
    pump_with_meter(client)
    client.post("/log/glucose", data={"value": "55", "measured_at": local(10)})
    first = reminder_of(engine, ReminderKind.HYPO_RECHECK).next_due_at
    client.post(
        "/log/hypo", data={"treatment": "juice", "carbs_grams": "15", "treated_at": local()}
    )
    later = reminder_of(engine, ReminderKind.HYPO_RECHECK).next_due_at
    assert first is not None
    assert later is not None
    assert later > first
