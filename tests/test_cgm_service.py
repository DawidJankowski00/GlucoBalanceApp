"""CGM settings, idempotent import, polling with backoff, and live alerts."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.cgm.base import CGMReading
from glucobalance.cgm.crypto import SecretBox, new_key
from glucobalance.cgm_service import (
    CGMRuntime,
    CGMSettingsError,
    LibreLinkUpInput,
    backoff,
    check_alert,
    is_due,
    list_patients,
    live_status,
    poll_connection,
    poll_due,
    save_librelinkup,
    store_readings,
    use_simulator,
)
from glucobalance.models import (
    CGMConnection,
    CGMSourceKind,
    DeliveryMode,
    GlucoseAlertKind,
    GlucoseReading,
    MonitoringMode,
    Notification,
    ReadingSource,
    Trend,
    User,
    UserSettings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "librelinkup"
NOW = datetime(2026, 10, 9, 18, 22, tzinfo=UTC)
EU = "https://api-eu.libreview.io"
GLOBAL = "https://api.libreview.io"
PATIENT = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
PASSWORD = "s3cret-pass"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(new_key())


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


def make_user(session: Session, monitoring: MonitoringMode = MonitoringMode.CGM) -> User:
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=DeliveryMode.PUMP,
            monitoring_mode=monitoring,
            max_bolus_units=Decimal("10"),
            timezone="UTC",
        )
    )
    session.flush()
    return user


def libre(session: Session, user: User, box: SecretBox, **changes: Any) -> CGMConnection:
    data = LibreLinkUpInput(enabled=True, email="follower@example.com", password=PASSWORD)
    return save_librelinkup(session, user, _replace(data, **changes), box)


def _replace(data: LibreLinkUpInput, **changes: Any) -> LibreLinkUpInput:
    values = {f: getattr(data, f) for f in LibreLinkUpInput.__dataclass_fields__}
    values.update(changes)
    return LibreLinkUpInput(**values)


def readings(session: Session, user: User) -> list[GlucoseReading]:
    return list(
        session.query(GlucoseReading)
        .filter_by(user_id=user.id)
        .order_by(GlucoseReading.measured_at)
    )


# ---------- settings ----------


def test_the_password_is_stored_encrypted(session: Session, box: SecretBox) -> None:
    connection = libre(session, make_user(session), box)

    assert connection.password_encrypted is not None
    assert PASSWORD not in connection.password_encrypted
    assert box.decrypt(connection.password_encrypted) == PASSWORD
    assert connection.source is CGMSourceKind.LIBRELINKUP
    assert connection.enabled


def test_a_blank_password_keeps_the_stored_one(session: Session, box: SecretBox) -> None:
    user = make_user(session)
    first = libre(session, user, box).password_encrypted

    connection = libre(session, user, box, password="", auto_accept_terms=False)

    assert connection.password_encrypted == first
    assert connection.auto_accept_terms is False


def test_turning_on_without_a_password_is_refused(session: Session, box: SecretBox) -> None:
    with pytest.raises(CGMSettingsError, match="password"):
        libre(session, make_user(session), box, password=None)


def test_without_a_key_the_password_is_not_stored(session: Session) -> None:
    with pytest.raises(CGMSettingsError, match="GBA_CGM_SECRET_KEY"):
        libre(session, make_user(session), None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"email": "not-an-email"}, "e-mail"),
        ({"server": "example.com"}, "server"),
        ({"poll_minutes": 0}, "between 1 and 5"),
        ({"poll_minutes": 6}, "between 1 and 5"),
    ],
)
def test_invalid_settings_are_refused(
    session: Session, box: SecretBox, changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(CGMSettingsError, match=message):
        libre(session, make_user(session), box, **changes)


def test_changing_the_login_forgets_the_token_and_patient(session: Session, box: SecretBox) -> None:
    user = make_user(session)
    connection = libre(session, user, box)
    connection.token_encrypted = box.encrypt("t")
    connection.token_expires_at = NOW + timedelta(days=1)
    connection.account_id = "id"
    connection.patient_id = PATIENT

    libre(session, user, box, email="other@example.com", password="")

    assert connection.token_encrypted is None
    assert connection.patient_id is None


def test_reconnect_asks_for_a_fresh_login(session: Session, box: SecretBox) -> None:
    connection = libre(session, make_user(session), box, reconnect=True)

    assert connection.reconnect_requested


def test_switching_to_the_simulator(session: Session, box: SecretBox) -> None:
    user = make_user(session)
    libre(session, user, box)

    connection = use_simulator(session, user, enabled=True)

    assert connection.source is CGMSourceKind.SIMULATOR
    assert connection.enabled


# ---------- storing ----------


def test_store_readings_is_idempotent_and_skips_impossible_values(session: Session) -> None:
    user = make_user(session)
    connection = use_simulator(session, user, enabled=True)
    batch = [
        CGMReading(NOW - timedelta(minutes=10), 120, Trend.STEADY),
        CGMReading(NOW - timedelta(minutes=5), 39),  # below the sensor range
        CGMReading(NOW, 118, Trend.FALLING),
    ]

    assert store_readings(session, connection, batch) == 2
    assert store_readings(session, connection, batch) == 0
    stored = readings(session, user)
    assert [r.value_mgdl for r in stored] == [120, 118]
    assert {r.source for r in stored} == {ReadingSource.SIMULATED}
    assert connection.last_reading_at == NOW


# ---------- due and backoff ----------


@pytest.mark.parametrize(
    ("failures", "minutes", "slow_down", "expected"),
    [
        (1, 1, False, 1),
        (2, 1, False, 2),
        (3, 5, False, 20),
        (1, 1, True, 5),
        (2, 1, True, 10),
        (10, 5, True, 60),  # capped at an hour
    ],
)
def test_backoff_doubles_and_is_capped(
    failures: int, minutes: int, slow_down: bool, expected: int
) -> None:
    assert backoff(failures, minutes, slow_down=slow_down) == timedelta(minutes=expected)


def test_is_due_respects_the_interval_and_retry_after(session: Session) -> None:
    connection = use_simulator(session, make_user(session), enabled=True)
    assert is_due(connection, NOW)

    connection.last_poll_at = NOW
    assert not is_due(connection, NOW + timedelta(minutes=4))
    assert is_due(connection, NOW + timedelta(minutes=5))

    connection.retry_after = NOW + timedelta(minutes=30)
    assert not is_due(connection, NOW + timedelta(minutes=10))

    connection.retry_after = None
    connection.enabled = False
    assert not is_due(connection, NOW + timedelta(hours=1))


# ---------- polling: simulator ----------


def sim_runtime(http: httpx.Client, trace: list[int]) -> CGMRuntime:
    return CGMRuntime(http=http, box=None, trace=lambda: trace)


def test_simulator_poll_imports_history_once(session: Session, http: httpx.Client) -> None:
    user = make_user(session)
    connection = use_simulator(session, user, enabled=True)
    runtime = sim_runtime(http, [100, 110, 120])

    first = poll_connection(session, connection, runtime, now=NOW)
    again = poll_connection(session, connection, runtime, now=NOW)

    assert first == 12 * 12  # 12 hours of 5-minute readings
    assert again == 0
    assert connection.last_success_at == NOW
    assert connection.last_reading_at == datetime(2026, 10, 9, 18, 20, tzinfo=UTC)


# ---------- polling: LibreLinkUp ----------


def libre_runtime(http: httpx.Client, box: SecretBox) -> CGMRuntime:
    return CGMRuntime(http=http, box=box)


def mock_libre(mock: respx.MockRouter) -> dict[str, respx.Route]:
    return {
        "login": mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_redirect")),
        "eu_login": mock.post(f"{EU}/llu/auth/login").respond(json=fixture("login_ok")),
        "connections": mock.get(f"{EU}/llu/connections").respond(json=fixture("connections")),
        "graph": mock.get(f"{EU}/llu/connections/{PATIENT}/graph").respond(json=fixture("graph")),
    }


def test_librelinkup_poll_stores_readings_and_caches_the_login(
    session: Session, http: httpx.Client, box: SecretBox, mock: respx.MockRouter
) -> None:
    routes = mock_libre(mock)
    user = make_user(session)
    connection = libre(session, user, box)
    runtime = libre_runtime(http, box)

    added = poll_connection(session, connection, runtime, now=NOW)

    assert added == 5
    assert readings(session, user)[-1].trend is Trend.FALLING
    assert {r.source for r in readings(session, user)} == {ReadingSource.CGM}
    assert connection.patient_id == PATIENT
    assert connection.region == "eu"
    assert connection.token_encrypted is not None
    assert "fake-token-1" not in connection.token_encrypted
    assert box.decrypt(connection.token_encrypted) == "fake-token-1"
    assert connection.last_error is None

    poll_connection(session, connection, runtime, now=NOW + timedelta(minutes=5))

    assert routes["eu_login"].call_count == 1  # the cached token was reused
    assert routes["connections"].call_count == 1  # the patient was remembered
    assert routes["graph"].call_count == 2


def test_reconnect_logs_in_again_even_with_a_valid_token(
    session: Session, http: httpx.Client, box: SecretBox, mock: respx.MockRouter
) -> None:
    routes = mock_libre(mock)
    user = make_user(session)
    connection = libre(session, user, box)
    runtime = libre_runtime(http, box)
    poll_connection(session, connection, runtime, now=NOW)

    libre(session, user, box, password="", reconnect=True)
    poll_connection(session, connection, runtime, now=NOW + timedelta(minutes=1))

    assert routes["eu_login"].call_count == 2
    assert not connection.reconnect_requested


def test_429_backs_off_and_records_the_error(
    session: Session, http: httpx.Client, box: SecretBox, mock: respx.MockRouter
) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(429)
    connection = libre(session, make_user(session), box)

    poll_connection(session, connection, libre_runtime(http, box), now=NOW)

    assert connection.failure_count == 1
    assert connection.retry_after == NOW + timedelta(minutes=5)
    assert connection.last_error is not None
    assert "too many requests" in connection.last_error
    assert not is_due(connection, NOW + timedelta(minutes=4))


def test_a_refused_password_is_shown_and_never_stored_in_the_error(
    session: Session, http: httpx.Client, box: SecretBox, mock: respx.MockRouter
) -> None:
    mock.post(f"{GLOBAL}/llu/auth/login").respond(json=fixture("login_bad_credentials"))
    connection = libre(session, make_user(session), box)

    poll_connection(session, connection, libre_runtime(http, box), now=NOW)

    assert connection.last_error == "LibreLinkUp refused the e-mail or password."
    assert connection.token_encrypted is None


def test_a_missing_key_is_reported_on_the_connection(
    session: Session, http: httpx.Client, box: SecretBox
) -> None:
    connection = libre(session, make_user(session), box)

    poll_connection(session, connection, CGMRuntime(http=http, box=None), now=NOW)

    assert connection.last_error is not None
    assert "GBA_CGM_SECRET_KEY" in connection.last_error


def test_list_patients(
    session: Session, http: httpx.Client, box: SecretBox, mock: respx.MockRouter
) -> None:
    mock_libre(mock)
    connection = libre(session, make_user(session), box)

    [patient] = list_patients(session, connection, libre_runtime(http, box), now=NOW)

    assert patient.name == "Pat Example"
    assert connection.token_encrypted is not None


# ---------- alerts ----------


def add_reading(session: Session, user: User, value: int, at: datetime, trend: Trend) -> None:
    session.add(
        GlucoseReading(
            user_id=user.id,
            measured_at=at,
            value_mgdl=value,
            source=ReadingSource.SIMULATED,
            trend=trend,
        )
    )
    session.flush()


def test_a_low_alerts_once_per_episode_and_clears_on_recovery(session: Session) -> None:
    user = make_user(session)
    assert user.settings is not None
    connection = use_simulator(session, user, enabled=True)
    add_reading(session, user, 62, NOW - timedelta(minutes=2), Trend.FALLING)
    connection.last_reading_at = NOW - timedelta(minutes=2)

    first = check_alert(session, connection, user.settings, now=NOW)
    second = check_alert(session, connection, user.settings, now=NOW + timedelta(minutes=5))

    assert first is not None
    assert first.title == "Low glucose"
    assert second is None
    assert connection.alert_kind is GlucoseAlertKind.LOW

    add_reading(session, user, 95, NOW + timedelta(minutes=8), Trend.RISING)
    connection.last_reading_at = NOW + timedelta(minutes=8)
    assert check_alert(session, connection, user.settings, now=NOW + timedelta(minutes=9)) is None
    assert connection.alert_kind is None


def test_quiet_hours_hold_a_high_but_not_a_low(session: Session) -> None:
    user = make_user(session)
    assert user.settings is not None
    user.settings.quiet_start, user.settings.quiet_end = time(17, 0), time(23, 0)
    connection = use_simulator(session, user, enabled=True)
    add_reading(session, user, 250, NOW - timedelta(minutes=1), Trend.STEADY)
    connection.last_reading_at = NOW - timedelta(minutes=1)

    assert check_alert(session, connection, user.settings, now=NOW) is None
    assert connection.alert_kind is None  # not sent, so it fires once quiet hours end


def test_no_alerts_in_glucometer_mode(session: Session) -> None:
    user = make_user(session, MonitoringMode.GLUCOMETER)
    assert user.settings is not None
    connection = use_simulator(session, user, enabled=True)
    add_reading(session, user, 50, NOW - timedelta(minutes=1), Trend.STEADY)
    connection.last_reading_at = NOW - timedelta(minutes=1)

    assert check_alert(session, connection, user.settings, now=NOW) is None


def test_poll_due_imports_and_alerts(session: Session, http: httpx.Client) -> None:
    user = make_user(session)
    use_simulator(session, user, enabled=True)

    created = poll_due(session, sim_runtime(http, [60]), now=NOW)

    assert [n.title for n in created] == ["Low glucose"]
    assert session.query(Notification).count() == 1
    assert readings(session, user)


def test_poll_due_skips_glucometer_users(session: Session, http: httpx.Client) -> None:
    user = make_user(session, MonitoringMode.GLUCOMETER)
    use_simulator(session, user, enabled=True)

    assert poll_due(session, sim_runtime(http, [60]), now=NOW) == []
    assert readings(session, user) == []


def test_live_status(session: Session, http: httpx.Client) -> None:
    user = make_user(session)
    connection = use_simulator(session, user, enabled=True)
    poll_connection(session, connection, sim_runtime(http, [100, 105]), now=NOW)

    status = live_status(session, user, now=NOW)

    assert status.latest is not None
    assert status.latest.measured_at == datetime(2026, 10, 9, 18, 20, tzinfo=UTC)
    assert not status.stale
    assert len(status.recent) == 36
    assert live_status(session, user, now=NOW + timedelta(minutes=20)).stale


def test_alert_text_never_holds_a_glucose_value(session: Session) -> None:
    from glucobalance.cgm_service import ALERT_TEXT

    for title, body in ALERT_TEXT.values():
        assert "mg/dL" not in title + body
        assert not any(ch.isdigit() for ch in title)
