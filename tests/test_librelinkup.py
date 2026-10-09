"""The LibreLinkUp client, tested offline against recorded replies (respx).

respx replaces httpx's network layer: each test declares which URL gets which reply, and any
request it did not declare fails the test. Nothing here reaches Abbott's servers.
"""

import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from glucobalance.cgm.base import CGMAuthError, CGMError, CGMRateLimited
from glucobalance.cgm.librelinkup import (
    DEFAULT_VERSION,
    LibreLinkUpClient,
    LibreLinkUpSource,
    LluLogin,
    parse_timestamp,
)
from glucobalance.models import Trend

FIXTURES = Path(__file__).parent / "fixtures" / "librelinkup"
NOW = datetime(2026, 10, 9, 18, 30, tzinfo=UTC)
PATIENT = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
USER_ID = "11111111-2222-3333-4444-555555555555"
GLOBAL = "https://api.libreview.io"
EU = "https://api-eu.libreview.io"
PASSWORD = "s3cret-pass"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client


def make_client(http: httpx.Client, **kwargs: Any) -> LibreLinkUpClient:
    return LibreLinkUpClient(http, "follower@example.com", PASSWORD, clock=lambda: NOW, **kwargs)


def valid_login() -> LluLogin:
    return LluLogin(token="cached-token", expires_at=NOW + timedelta(days=30), account_id=USER_ID)


# ---------- timestamps ----------


def test_factory_timestamps_are_utc() -> None:
    assert parse_timestamp("10/9/2026 6:20:00 PM") == datetime(2026, 10, 9, 18, 20, tzinfo=UTC)
    assert parse_timestamp("1/2/2026 12:05:09 AM") == datetime(2026, 1, 2, 0, 5, 9, tzinfo=UTC)


# ---------- login ----------


def test_login_follows_the_regional_redirect(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_redirect"))
    regional = mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_ok"))
    client = make_client(http)

    login = client.login()

    assert regional.called
    assert client.region == "eu"
    assert login.token == "fake-token-1"
    assert login.account_id == USER_ID
    assert login.expires_at == datetime(2027, 4, 6, 8, 26, 40, tzinfo=UTC)


def test_login_sends_the_app_headers_and_credentials(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    route = mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_ok"))

    make_client(http).login()

    request = route.calls.last.request
    assert request.headers["product"] == "llu.android"
    assert request.headers["version"] == DEFAULT_VERSION
    assert "Authorization" not in request.headers
    assert json.loads(request.content) == {"email": "follower@example.com", "password": PASSWORD}


def test_wrong_password_is_an_auth_error(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_bad_credentials"))

    with pytest.raises(CGMAuthError, match="e-mail or password"):
        make_client(http).login()


def test_new_terms_are_accepted_when_allowed(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_terms"))
    accept = mock.post(f"{GLOBAL}/auth/continue/tou").respond(json=fixture("login_ok"))

    login = make_client(http, auto_accept_terms=True).login()

    assert accept.called
    assert accept.calls.last.request.headers["Authorization"] == "Bearer fake-step-token"
    assert login.token == "fake-token-1"


def test_new_terms_stop_the_login_when_not_allowed(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_terms"))
    accept = mock.post(f"{GLOBAL}/auth/continue/tou")

    with pytest.raises(CGMAuthError, match="new terms of use"):
        make_client(http, auto_accept_terms=False).login()
    assert not accept.called


def test_the_same_step_twice_is_not_accepted_in_a_loop(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_terms"))
    mock.post(f"{GLOBAL}/auth/continue/tou").respond(json=fixture("login_terms"))

    with pytest.raises(CGMAuthError, match="LibreLinkUp app"):
        make_client(http).login()


def test_a_too_old_version_is_retried_with_the_minimum(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    route = mock.post(f"{GLOBAL}/llu/auth/login")
    route.side_effect = [
        httpx.Response(403, json=fixture("version_too_old")),
        httpx.Response(200, json=fixture("login_ok")),
    ]
    client = make_client(http)

    client.login()

    assert client.version == "4.18.0"
    assert route.calls.last.request.headers["version"] == "4.18.0"


def test_429_raises_rate_limited(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(429)

    with pytest.raises(CGMRateLimited):
        make_client(http).login()


def test_network_failure_is_a_cgm_error(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(CGMError, match="Could not reach"):
        make_client(http).login()


def test_a_reply_that_is_not_json_is_a_cgm_error(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(200, text="<html>maintenance</html>")

    with pytest.raises(CGMError, match="not JSON"):
        make_client(http).login()


def test_an_unknown_server_is_refused(http: httpx.Client) -> None:
    with pytest.raises(ValueError, match="server"):
        make_client(http, server="example.com")


# ---------- token reuse ----------


def test_a_valid_cached_token_is_reused_without_login(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    login = mock.post(f"{EU}/llu/auth/login")
    graph = mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph"))
    client = make_client(http, region="eu", login=valid_login())

    client.graph(PATIENT)

    assert not login.called
    headers = graph.calls.last.request.headers
    assert headers["Authorization"] == "Bearer cached-token"
    assert headers["Account-Id"] == hashlib.sha256(USER_ID.encode()).hexdigest()


def test_an_expired_token_logs_in_again(mock: respx.MockRouter, http: httpx.Client) -> None:
    login = mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_ok"))
    mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph"))
    expired = LluLogin(token="old", expires_at=NOW - timedelta(seconds=1), account_id=USER_ID)
    client = make_client(http, region="eu", login=expired)

    client.graph(PATIENT)

    assert login.call_count == 1
    assert client.login_state is not None
    assert client.login_state.token == "fake-token-1"


def test_a_revoked_token_logs_in_once_and_retries(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    login = mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_ok"))
    graph = mock.get(f"{EU}/llu/connections/{PATIENT}/graph")
    graph.side_effect = [httpx.Response(401), httpx.Response(200, json=fixture("graph"))]
    client = make_client(http, region="eu", login=valid_login())

    readings = client.graph(PATIENT)

    assert login.call_count == 1
    assert graph.call_count == 2
    assert readings


# ---------- data ----------


def test_patients_lists_the_followed_people(mock: respx.MockRouter, http: httpx.Client) -> None:
    mock.get(f"{EU}/llu/connections").respond(json=fixture("connections"))
    client = make_client(http, region="eu", login=valid_login())

    [patient] = client.patients()

    assert patient.patient_id == PATIENT
    assert patient.name == "Pat Example"


def test_graph_merges_history_and_the_current_value(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph"))
    client = make_client(http, region="eu", login=valid_login())

    readings = client.graph(PATIENT)

    assert [r.value_mgdl for r in readings] == [131, 125, 119, 115, 112]  # bad row skipped
    assert readings == sorted(readings, key=lambda r: r.measured_at)
    assert readings[-1].measured_at == datetime(2026, 10, 9, 18, 20, tzinfo=UTC)
    assert readings[-1].trend is Trend.FALLING
    assert readings[0].trend is None  # history has no arrows


def test_a_strange_patient_id_is_refused(http: httpx.Client) -> None:
    client = make_client(http, region="eu", login=valid_login())

    with pytest.raises(ValueError):
        client.graph("../../auth")


# ---------- the CGMSource adapter ----------


def test_source_picks_the_first_patient_and_filters_by_time(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.get(f"{EU}/llu/connections").respond(json=fixture("connections"))
    mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph"))
    source = LibreLinkUpSource(make_client(http, region="eu", login=valid_login()))

    readings = source.fetch_readings(datetime(2026, 10, 9, 18, 10, tzinfo=UTC))

    assert source.patient_id == PATIENT
    assert [r.value_mgdl for r in readings] == [115, 112]


def test_source_with_nobody_followed_explains_the_setup(
    mock: respx.MockRouter, http: httpx.Client
) -> None:
    mock.get(f"{EU}/llu/connections").respond(json=fixture("connections_empty"))
    source = LibreLinkUpSource(make_client(http, region="eu", login=valid_login()))

    with pytest.raises(CGMError, match="follows nobody"):
        source.fetch_readings(NOW - timedelta(hours=1))


def test_the_password_and_token_never_reach_the_log(
    mock: respx.MockRouter, http: httpx.Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_redirect"))
    mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_terms"))
    mock.post(f"{EU}/auth/continue/tou").respond(json=fixture("login_ok"))
    client = make_client(http)

    client.login()

    for secret in (PASSWORD, "fake-token-1", "fake-step-token"):
        assert secret not in caplog.text
        assert secret not in repr(client)
