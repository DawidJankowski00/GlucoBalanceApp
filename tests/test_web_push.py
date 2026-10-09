"""The push endpoints, the service worker and the reminders-page controls."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.config import Settings
from glucobalance.main import create_app
from glucobalance.models import PushSubscription
from glucobalance.push import PushPayload, PushTarget
from test_web import onboard, saved_user, sign_up

SUBSCRIPTION = {
    "endpoint": "https://push.example/abc",
    "keys": {"p256dh": "public-key", "auth": "auth-secret"},
}


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[PushTarget, PushPayload]] = []

    def send(self, target: PushTarget, payload: PushPayload) -> None:
        self.sent.append((target, payload))


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def push_client(engine: Engine, sender: RecordingSender) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        secret_key="test-secret-key",
        vapid_private_key="private",
        vapid_public_key="BPublicKey",
    )
    with TestClient(create_app(settings, engine, push_sender=sender)) as client:
        sign_up(client)
        onboard(client)
        yield client


def test_the_service_worker_is_served_from_the_root(client: TestClient) -> None:
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "showNotification" in response.text


def test_push_endpoints_need_login(client: TestClient) -> None:
    for method, path in (("get", "/push/status"), ("post", "/push/subscribe")):
        response = getattr(client, method)(path, follow_redirects=False)
        assert response.status_code == 303


def test_status_without_keys_says_push_is_off(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    assert client.get("/push/status").json() == {"enabled": False, "key": None, "devices": 0}


def test_status_with_keys_hands_the_browser_the_public_key_only(push_client: TestClient) -> None:
    info = push_client.get("/push/status").json()
    assert info == {"enabled": True, "key": "BPublicKey", "devices": 0}
    assert "private" not in push_client.get("/push/status").text


def test_subscribe_and_unsubscribe(push_client: TestClient, engine: Engine) -> None:
    assert push_client.post("/push/subscribe", json=SUBSCRIPTION).status_code == 204
    assert push_client.get("/push/status").json()["devices"] == 1
    session, user = saved_user(engine)
    with session:
        (stored,) = session.query(PushSubscription).all()
        assert stored.user_id == user.id
        assert (stored.p256dh, stored.auth) == ("public-key", "auth-secret")

    assert push_client.post("/push/unsubscribe", json={"endpoint": SUBSCRIPTION["endpoint"]})
    assert push_client.get("/push/status").json()["devices"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"endpoint": "http://insecure.example/x", "keys": {"p256dh": "k", "auth": "a"}},
        {"endpoint": "https://push.example/x", "keys": {}},
        {"endpoint": "https://push.example/x", "keys": "nope"},
    ],
)
def test_a_bad_subscription_is_refused(push_client: TestClient, body: dict[str, object]) -> None:
    response = push_client.post("/push/subscribe", json=body)
    assert response.status_code == 422
    assert "error" in response.json()


def test_a_body_that_is_not_json_is_refused(push_client: TestClient) -> None:
    response = push_client.post(
        "/push/subscribe", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_the_test_button_sends_to_the_users_devices(
    push_client: TestClient, sender: RecordingSender
) -> None:
    push_client.post("/push/subscribe", json=SUBSCRIPTION)
    response = push_client.post("/push/test")
    assert response.json() == {"sent": 1}
    ((target, payload),) = sender.sent
    assert target.endpoint == SUBSCRIPTION["endpoint"]
    assert payload.url == "/notifications"


def test_the_test_button_explains_when_push_is_not_set_up(client: TestClient) -> None:
    sign_up(client)
    onboard(client)
    response = client.post("/push/test")
    assert response.status_code == 422
    assert "not set up" in response.json()["error"]


def test_the_reminders_page_has_the_phone_controls(push_client: TestClient) -> None:
    page = push_client.get("/reminders").text
    assert "Phone notifications" in page
    assert "/sw.js" in page
