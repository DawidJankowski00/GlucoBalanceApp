"""Rate limiting, the cross-site guard, security headers and the login limits."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.config import Settings
from glucobalance.main import create_app
from glucobalance.security import RateLimiter
from test_web import PASSWORD, sign_up


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_the_limit_then_blocks() -> None:
    limiter = RateLimiter(limit=3, window_seconds=60, clock=FakeClock())
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_limiter_keys_are_independent() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=FakeClock())
    assert limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("a")


def test_limiter_frees_up_as_the_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.allow("a")
    clock.now += 30
    limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.retry_after("a") == 31
    clock.now += 31  # the first hit is now older than the window
    assert limiter.retry_after("a") == 0
    assert limiter.allow("a")


def test_blocked_attempts_do_not_extend_the_block() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.allow("a")
    for _ in range(5):
        clock.now += 10
        assert not limiter.allow("a")
    clock.now += 11
    assert limiter.allow("a")


def test_reset_clears_a_key() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=FakeClock())
    limiter.allow("a")
    limiter.reset("a")
    assert limiter.allow("a")


def test_cross_site_post_is_refused(client: TestClient) -> None:
    response = client.post("/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_cross_origin_post_without_fetch_metadata_is_refused(client: TestClient) -> None:
    assert client.post("/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/logout", headers={"Origin": "null"}).status_code == 403


def test_same_origin_post_is_allowed(client: TestClient) -> None:
    same = client.post("/logout", headers={"Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 200  # followed the redirect to the login page
    origin = client.post("/logout", headers={"Origin": "http://testserver"})
    assert origin.status_code == 200


def test_cross_site_get_is_not_blocked(client: TestClient) -> None:
    assert client.get("/login", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_security_headers_are_set(client: TestClient) -> None:
    headers = client.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "strict-transport-security" not in headers


def test_hsts_is_sent_in_production(engine: Engine) -> None:
    settings = Settings(environment="production", secret_key="a-private-production-key")
    with TestClient(create_app(settings, engine), base_url="https://testserver") as client:
        assert "max-age" in client.get("/health").headers["strict-transport-security"]


def test_repeated_failed_logins_are_blocked(client: TestClient) -> None:
    sign_up(client)
    client.post("/logout")
    for _ in range(8):
        wrong = client.post("/login", data={"email": "ann@example.com", "password": "nope"})
        assert wrong.status_code == 401
    blocked = client.post("/login", data={"email": "ann@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.text


def test_a_good_login_resets_the_email_counter(client: TestClient) -> None:
    sign_up(client)
    good = {"email": "ann@example.com", "password": PASSWORD}
    bad = {"email": "ann@example.com", "password": "nope"}
    client.post("/logout")
    for _ in range(5):
        client.post("/login", data=bad)
    assert client.post("/login", data=good).status_code == 200
    client.post("/logout")
    for _ in range(7):
        client.post("/login", data=bad)
    assert client.post("/login", data=good).status_code == 200


def test_signups_are_limited_per_address(client: TestClient) -> None:
    for number in range(10):
        client.post(
            "/signup",
            data={"email": f"u{number}@example.com", "display_name": "U", "password": PASSWORD},
        )
        client.post("/logout")
    response = client.post(
        "/signup", data={"email": "late@example.com", "display_name": "U", "password": PASSWORD}
    )
    assert response.status_code == 429


def test_forwarded_header_is_ignored_unless_the_proxy_is_trusted(engine: Engine) -> None:
    def blocked_after(trust_proxy: bool) -> int:
        settings = Settings(
            environment="test", secret_key="test-secret-key", trust_proxy=trust_proxy
        )
        with TestClient(create_app(settings, engine)) as client:
            for number in range(10):
                forged = {"X-Forwarded-For": f"10.0.0.{number}"}
                client.post(
                    "/signup",
                    data={
                        "email": f"p{number}@example.com",
                        "display_name": "P",
                        "password": PASSWORD,
                    },
                    headers=forged,
                )
                client.post("/logout")
            late = client.post(
                "/signup",
                data={"email": "late@example.com", "display_name": "P", "password": PASSWORD},
                headers={"X-Forwarded-For": "10.0.0.99"},
            )
            return int(late.status_code)

    assert blocked_after(trust_proxy=False) == 429  # forging the header changes nothing
    assert blocked_after(trust_proxy=True) == 200  # a proxy-supplied address is its own bucket
