"""Web Push: store each browser's subscription and send it a message when a reminder fires.

How it works: the browser asks its vendor's push service for a private "mailbox" URL (the
subscription ``endpoint``) plus two keys. We keep those. To notify, we POST an encrypted
message to the endpoint, signed with our VAPID key so the push service knows who is calling.
The phone's browser wakes its service worker, which shows the notification, even when the
app is closed.

``deliver`` never raises for a push problem: the in-app notification is already saved, and a
broken push service must not stop the scheduler.
"""

import base64
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from glucobalance.models import Notification, PushSubscription, User
from glucobalance.reminder_service import ReminderError
from glucobalance.repositories import PushSubscriptionRepository

log = logging.getLogger(__name__)

NOTIFICATIONS_URL = "/notifications"
GONE_STATUSES = frozenset({404, 410})
MAX_FIELD_LENGTH = 512


class SubscriptionGone(Exception):
    """The push service says this subscription no longer exists (the user revoked it)."""


@dataclass(frozen=True, slots=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True, slots=True)
class PushPayload:
    title: str
    body: str
    url: str

    def to_json(self) -> str:
        return json.dumps({"title": self.title, "body": self.body, "url": self.url})


class PushSender(Protocol):
    def send(self, target: PushTarget, payload: PushPayload) -> None:
        """Send one message. Raise ``SubscriptionGone`` if the subscription is dead."""
        ...


class WebPushSender:
    """Sends through ``pywebpush``, signing with our VAPID private key."""

    def __init__(self, private_key: str, contact: str) -> None:
        self._private_key = private_key
        self._claims = {"sub": contact}

    def send(self, target: PushTarget, payload: PushPayload) -> None:
        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=payload.to_json(),
                vapid_private_key=self._private_key,
                vapid_claims=dict(self._claims),
            )
        except WebPushException as error:
            status = getattr(error.response, "status_code", None)
            if status in GONE_STATUSES:
                raise SubscriptionGone(target.endpoint) from error
            raise


def generate_vapid_keys() -> tuple[str, str]:
    """A new VAPID key pair as (private, public), both URL-safe base64 without padding.

    The private key goes in ``GBA_VAPID_PRIVATE_KEY`` on the server; the public key goes in
    ``GBA_VAPID_PUBLIC_KEY`` and is handed to the browser when it subscribes.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64(private), _b64(public)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---------- subscriptions ----------


def subscribe(
    session: Session, user: User, *, endpoint: str, p256dh: str, auth: str, now: datetime
) -> PushSubscription:
    """Remember a browser. The same endpoint again updates its keys; it belongs to one user."""
    endpoint, p256dh, auth = endpoint.strip(), p256dh.strip(), auth.strip()
    if not endpoint.startswith("https://") or len(endpoint) > 2048:
        raise ReminderError("That browser did not give a valid notification address.")
    if not p256dh or not auth or len(p256dh) > MAX_FIELD_LENGTH or len(auth) > MAX_FIELD_LENGTH:
        raise ReminderError("That browser did not give valid notification keys.")
    repository = PushSubscriptionRepository(session)
    existing = repository.by_endpoint(endpoint)
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = p256dh
        existing.auth = auth
        session.flush()
        return existing
    return repository.add(
        PushSubscription(
            user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, created_at=now
        )
    )


def unsubscribe(session: Session, user: User, endpoint: str) -> None:
    repository = PushSubscriptionRepository(session)
    existing = repository.by_endpoint(endpoint.strip())
    if existing is not None and existing.user_id == user.id:
        repository.delete(existing)


def subscriptions_for(session: Session, user: User) -> Sequence[PushSubscription]:
    return PushSubscriptionRepository(session).for_user(user.id)


# ---------- delivery ----------


def deliver(
    session: Session, notifications: Sequence[Notification], sender: PushSender | None
) -> int:
    """Push each notification to every device its user has. Returns how many messages went out."""
    if sender is None:
        return 0
    repository = PushSubscriptionRepository(session)
    sent = 0
    for notification in notifications:
        payload = PushPayload(notification.title, notification.body or "", NOTIFICATIONS_URL)
        for subscription in repository.for_user(notification.user_id):
            target = PushTarget(subscription.endpoint, subscription.p256dh, subscription.auth)
            try:
                sender.send(target, payload)
            except SubscriptionGone:
                repository.delete(subscription)
            except Exception:
                # The endpoint is deliberately not logged: it is a private address.
                log.exception("Web Push failed for subscription %s", subscription.id)
            else:
                sent += 1
    return sent


if __name__ == "__main__":
    private_key, public_key = generate_vapid_keys()
    print("Add these to your .env (keep the private key secret):")
    print(f"GBA_VAPID_PRIVATE_KEY={private_key}")
    print(f"GBA_VAPID_PUBLIC_KEY={public_key}")
