"""Web Push: subscriptions, delivery with a fake sender, expired subscriptions, VAPID keys."""

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.models import (
    DeliveryMode,
    MonitoringMode,
    Notification,
    PushSubscription,
    User,
    UserSettings,
)
from glucobalance.push import (
    PushPayload,
    PushTarget,
    SubscriptionGone,
    WebPushSender,
    deliver,
    generate_vapid_keys,
    subscribe,
    subscriptions_for,
    unsubscribe,
)

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def make_user(session: Session, email: str = "ann@example.com") -> User:
    user = register(session, email, "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=DeliveryMode.PUMP,
            monitoring_mode=MonitoringMode.CGM,
            max_bolus_units=Decimal("10"),
        )
    )
    session.flush()
    return user


class FakeSender:
    def __init__(self, gone: set[str] | None = None, broken: set[str] | None = None) -> None:
        self.sent: list[tuple[PushTarget, PushPayload]] = []
        self.gone = gone or set()
        self.broken = broken or set()

    def send(self, target: PushTarget, payload: PushPayload) -> None:
        if target.endpoint in self.gone:
            raise SubscriptionGone(target.endpoint)
        if target.endpoint in self.broken:
            raise RuntimeError("push service down")
        self.sent.append((target, payload))


def notify(session: Session, user: User, title: str = "Check glucose") -> Notification:
    note = Notification(user_id=user.id, title=title, body="Time to check.", created_at=NOW)
    session.add(note)
    session.flush()
    return note


def sub(session: Session, user: User, endpoint: str = "https://push.example/a") -> PushSubscription:
    return subscribe(session, user, endpoint=endpoint, p256dh="key", auth="auth", now=NOW)


# ---------- subscriptions ----------


def test_subscribe_stores_the_browser(session: Session) -> None:
    user = make_user(session)
    sub(session, user)
    assert [s.endpoint for s in subscriptions_for(session, user)] == ["https://push.example/a"]


def test_subscribing_twice_with_the_same_endpoint_keeps_one_row(session: Session) -> None:
    user = make_user(session)
    sub(session, user)
    subscribe(session, user, endpoint="https://push.example/a", p256dh="new", auth="new", now=NOW)
    (only,) = subscriptions_for(session, user)
    assert only.p256dh == "new"


def test_a_browser_that_signs_in_as_someone_else_moves_to_that_user(session: Session) -> None:
    ann = make_user(session)
    bob = make_user(session, "bob@example.com")
    sub(session, ann)
    sub(session, bob)
    assert subscriptions_for(session, ann) == []
    assert len(subscriptions_for(session, bob)) == 1


@pytest.mark.parametrize(
    ("endpoint", "p256dh", "auth"),
    [
        ("", "k", "a"),
        ("http://push.example/insecure", "k", "a"),
        ("https://push.example/x", "", "a"),
        ("https://push.example/x", "k", ""),
    ],
)
def test_invalid_subscriptions_are_rejected(
    session: Session, endpoint: str, p256dh: str, auth: str
) -> None:
    from glucobalance.reminder_service import ReminderError

    user = make_user(session)
    with pytest.raises(ReminderError):
        subscribe(session, user, endpoint=endpoint, p256dh=p256dh, auth=auth, now=NOW)


def test_unsubscribe_removes_only_your_own(session: Session) -> None:
    ann = make_user(session)
    bob = make_user(session, "bob@example.com")
    sub(session, ann)
    unsubscribe(session, bob, "https://push.example/a")
    assert len(subscriptions_for(session, ann)) == 1
    unsubscribe(session, ann, "https://push.example/a")
    assert subscriptions_for(session, ann) == []


# ---------- delivery ----------


def test_each_notification_goes_to_each_of_the_users_devices(session: Session) -> None:
    user = make_user(session)
    sub(session, user, "https://push.example/phone")
    sub(session, user, "https://push.example/laptop")
    note = notify(session, user)
    sender = FakeSender()
    assert deliver(session, [note], sender) == 2
    assert {t.endpoint for t, _ in sender.sent} == {
        "https://push.example/phone",
        "https://push.example/laptop",
    }


def test_the_payload_carries_title_body_and_link(session: Session) -> None:
    user = make_user(session)
    sub(session, user)
    sender = FakeSender()
    deliver(session, [notify(session, user)], sender)
    ((_, payload),) = sender.sent
    assert payload == PushPayload(
        title="Check glucose", body="Time to check.", url="/notifications"
    )
    assert json.loads(payload.to_json()) == {
        "title": "Check glucose",
        "body": "Time to check.",
        "url": "/notifications",
    }


def test_users_only_get_their_own_notifications(session: Session) -> None:
    ann = make_user(session)
    bob = make_user(session, "bob@example.com")
    sub(session, bob)
    sender = FakeSender()
    assert deliver(session, [notify(session, ann)], sender) == 0
    assert sender.sent == []


def test_an_expired_subscription_is_removed(session: Session) -> None:
    user = make_user(session)
    sub(session, user, "https://push.example/dead")
    sub(session, user, "https://push.example/alive")
    sender = FakeSender(gone={"https://push.example/dead"})
    assert deliver(session, [notify(session, user)], sender) == 1
    assert [s.endpoint for s in subscriptions_for(session, user)] == ["https://push.example/alive"]


def test_a_failing_push_service_never_breaks_delivery_and_keeps_the_subscription(
    session: Session,
) -> None:
    user = make_user(session)
    sub(session, user, "https://push.example/flaky")
    sub(session, user, "https://push.example/fine")
    sender = FakeSender(broken={"https://push.example/flaky"})
    assert deliver(session, [notify(session, user)], sender) == 1
    assert len(subscriptions_for(session, user)) == 2


def test_without_a_sender_nothing_is_sent(session: Session) -> None:
    user = make_user(session)
    sub(session, user)
    assert deliver(session, [notify(session, user)], None) == 0


# ---------- the real sender ----------


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def fake_web_push_exception(status: int | None) -> Exception:
    from pywebpush import WebPushException

    error: Exception = WebPushException(
        "failed", response=None if status is None else FakeResponse(status)
    )
    return error


def test_the_web_push_sender_passes_keys_and_payload_to_pywebpush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("glucobalance.push.webpush", lambda **kwargs: calls.append(kwargs))
    sender = WebPushSender(private_key="PRIVATE", contact="mailto:me@example.com")
    sender.send(
        PushTarget(endpoint="https://push.example/a", p256dh="k", auth="a"),
        PushPayload("T", "B", "/notifications"),
    )
    (call,) = calls
    assert call["subscription_info"] == {
        "endpoint": "https://push.example/a",
        "keys": {"p256dh": "k", "auth": "a"},
    }
    assert call["vapid_private_key"] == "PRIVATE"
    assert call["vapid_claims"] == {"sub": "mailto:me@example.com"}
    assert json.loads(call["data"])["title"] == "T"


@pytest.mark.parametrize("status", [404, 410])
def test_a_404_or_410_means_the_subscription_is_gone(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def boom(**_: Any) -> None:
        raise fake_web_push_exception(status)

    monkeypatch.setattr("glucobalance.push.webpush", boom)
    sender = WebPushSender(private_key="PRIVATE", contact="mailto:me@example.com")
    with pytest.raises(SubscriptionGone):
        sender.send(PushTarget("https://push.example/a", "k", "a"), PushPayload("T", "B", "/"))


def test_other_failures_propagate_as_they_are(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: Any) -> None:
        raise fake_web_push_exception(500)

    monkeypatch.setattr("glucobalance.push.webpush", boom)
    sender = WebPushSender(private_key="PRIVATE", contact="mailto:me@example.com")
    with pytest.raises(Exception) as caught:
        sender.send(PushTarget("https://push.example/a", "k", "a"), PushPayload("T", "B", "/"))
    assert not isinstance(caught.value, SubscriptionGone)


# ---------- keys ----------


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_generated_vapid_keys_have_the_expected_shape() -> None:
    private, public = generate_vapid_keys()
    assert len(_b64(private)) == 32
    raw_public = _b64(public)
    assert len(raw_public) == 65
    assert raw_public[0] == 0x04  # an uncompressed P-256 point


def test_each_call_makes_new_keys() -> None:
    assert generate_vapid_keys() != generate_vapid_keys()
