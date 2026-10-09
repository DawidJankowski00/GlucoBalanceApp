"""CGM import: settings, polling, idempotent storage, backoff and live alerts.

This is the only module that joins the CGM adapters (``glucobalance.cgm``) to the database.
Like the other services, every function takes ``now`` so tests control the clock, flushes
through repositories and never commits.

One poll for one connection:

1. Skip it unless it is due (every ``poll_minutes``) and not backing off after an error.
2. Build the source: the simulator, or LibreLinkUp with the decrypted password and the
   cached token.
3. Fetch readings newer than the last stored one and insert only new timestamps.
4. Save the token for next time. On an error, record a message the user can read and wait
   longer before the next try (longer still after "429 Too Many Requests").
5. Work out the live alert and add a notification if one is due.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from glucobalance.cgm.alerts import Latest, classify, is_stale, should_send
from glucobalance.cgm.base import CGMAuthError, CGMError, CGMRateLimited, CGMReading, CGMSource
from glucobalance.cgm.crypto import SecretBox, SecretKeyError
from glucobalance.cgm.librelinkup import (
    DEFAULT_VERSION,
    SERVERS,
    LibreLinkUpClient,
    LibreLinkUpSource,
    LluLogin,
    LluPatient,
)
from glucobalance.cgm.simulator import SimulatorSource, default_trace
from glucobalance.entries import EntryError
from glucobalance.features import feature_flags
from glucobalance.models import (
    CGMConnection,
    CGMSourceKind,
    GlucoseAlertKind,
    GlucoseReading,
    Notification,
    ReadingSource,
    User,
    UserSettings,
)
from glucobalance.reminder_rules import in_quiet_hours
from glucobalance.reminder_service import quiet_hours_for
from glucobalance.repositories import (
    CGMConnectionRepository,
    GlucoseRepository,
    NotificationRepository,
)

log = logging.getLogger(__name__)

# Libre sensors read from 40 to 500 mg/dL; outside that they show LO or HI, not a number.
MIN_CGM_MGDL = 40
MAX_CGM_MGDL = 500
# The first poll fetches this much history (LibreLinkUp keeps about 12 hours).
FIRST_POLL_HISTORY = timedelta(hours=12)
MAX_BACKOFF = timedelta(hours=1)
# After a refused login or a 429, wait at least this long: retrying fast makes it worse.
SLOW_DOWN = timedelta(minutes=5)
EMAIL_MAX_LENGTH = 320
PATIENT_ID_MAX_LENGTH = 64

SOURCE_OF = {
    CGMSourceKind.LIBRELINKUP: ReadingSource.CGM,
    CGMSourceKind.SIMULATOR: ReadingSource.SIMULATED,
}


class CGMSettingsError(EntryError):
    """The CGM settings are not acceptable. The message can be shown to the user."""


@dataclass(frozen=True, slots=True)
class LibreLinkUpInput:
    enabled: bool
    email: str
    password: str | None  # None or empty keeps the stored password
    server: str = "io"
    auto_accept_terms: bool = True
    patient_id: str | None = None
    reconnect: bool = False
    poll_minutes: int = 5


@cache
def _cached_trace() -> tuple[int, ...]:  # pragma: no cover - runs simglucose when installed
    return tuple(default_trace())


@dataclass(slots=True)
class CGMRuntime:
    """What polling needs besides the database: an HTTP client, the key and the demo trace."""

    http: httpx.Client
    box: SecretBox | None
    trace: Callable[[], Sequence[int]] = field(default=_cached_trace)


# ---------- settings ----------


def get_connection(session: Session, user: User) -> CGMConnection | None:
    return CGMConnectionRepository(session).for_user(user.id)


def _connection(session: Session, user: User, source: CGMSourceKind) -> CGMConnection:
    connection = get_connection(session, user)
    if connection is None:
        connection = CGMConnectionRepository(session).add(
            CGMConnection(user_id=user.id, source=source, enabled=False)
        )
    return connection


def _reset_login(connection: CGMConnection) -> None:
    connection.token_encrypted = None
    connection.token_expires_at = None
    connection.account_id = None
    connection.region = None


def _reset_polling(connection: CGMConnection) -> None:
    connection.last_error = None
    connection.failure_count = 0
    connection.retry_after = None
    connection.last_poll_at = None


def save_librelinkup(
    session: Session, user: User, data: LibreLinkUpInput, box: SecretBox | None
) -> CGMConnection:
    """Save the LibreLinkUp follower settings. The password is stored only encrypted."""
    email = data.email.strip()
    if len(email) > EMAIL_MAX_LENGTH or (email and "@" not in email):
        raise CGMSettingsError("Enter the e-mail address of the LibreLinkUp follower account.")
    if data.server not in SERVERS:
        raise CGMSettingsError("Choose a LibreLinkUp server.")
    if not 1 <= data.poll_minutes <= 5:
        raise CGMSettingsError("Choose a polling interval between 1 and 5 minutes.")
    if data.patient_id and (
        len(data.patient_id) > PATIENT_ID_MAX_LENGTH
        or not data.patient_id.replace("-", "").isalnum()
    ):
        raise CGMSettingsError("Choose a patient from the list.")
    connection = _connection(session, user, CGMSourceKind.LIBRELINKUP)
    password = (data.password or "").strip()
    if password:
        if box is None:
            raise CGMSettingsError(
                "The server has no GBA_CGM_SECRET_KEY, so the password cannot be stored safely."
            )
        connection.password_encrypted = box.encrypt(password)
    login_changed = (
        connection.source is not CGMSourceKind.LIBRELINKUP
        or email != (connection.email or "")
        or data.server != connection.server
        or bool(password)
    )
    if data.enabled and not (email and connection.password_encrypted):
        raise CGMSettingsError("Enter the follower e-mail and password before turning it on.")
    if login_changed:
        _reset_login(connection)
        connection.patient_id = None
        _reset_polling(connection)
    elif data.patient_id is not None and data.patient_id != connection.patient_id:
        connection.patient_id = data.patient_id or None
    connection.source = CGMSourceKind.LIBRELINKUP
    connection.enabled = data.enabled
    connection.email = email or None
    connection.server = data.server
    connection.auto_accept_terms = data.auto_accept_terms
    connection.poll_minutes = data.poll_minutes
    if data.reconnect:
        connection.reconnect_requested = True
        _reset_polling(connection)
    if not data.enabled:
        connection.alert_kind = None
        connection.alert_sent_at = None
    session.flush()
    return connection


def use_simulator(session: Session, user: User, *, enabled: bool) -> CGMConnection:
    """Switch to (or away from) the simulated CGM used for demos.

    Switching it off leaves a LibreLinkUp connection alone.
    """
    connection = _connection(session, user, CGMSourceKind.SIMULATOR)
    if not enabled and connection.source is not CGMSourceKind.SIMULATOR:
        return connection
    if connection.source is not CGMSourceKind.SIMULATOR:
        connection.source = CGMSourceKind.SIMULATOR
        _reset_polling(connection)
        connection.last_reading_at = None
    connection.enabled = enabled
    connection.alert_kind = None
    connection.alert_sent_at = None
    session.flush()
    return connection


# ---------- storing ----------


def store_readings(
    session: Session, connection: CGMConnection, readings: Sequence[CGMReading]
) -> int:
    """Insert readings not stored yet; values outside the sensor range are skipped."""
    source = SOURCE_OF[connection.source]
    rows = [
        GlucoseReading(
            user_id=connection.user_id,
            measured_at=r.measured_at,
            value_mgdl=r.value_mgdl,
            source=source,
            trend=r.trend,
        )
        for r in readings
        if MIN_CGM_MGDL <= r.value_mgdl <= MAX_CGM_MGDL
    ]
    added = GlucoseRepository(session).add_new(rows)
    if rows:
        newest = max(r.measured_at for r in rows)
        if connection.last_reading_at is None or newest > connection.last_reading_at:
            connection.last_reading_at = newest
    return added


# ---------- polling ----------


def backoff(failure_count: int, poll_minutes: int, *, slow_down: bool) -> timedelta:
    """How long to wait after ``failure_count`` failures in a row (doubling, capped)."""
    base = max(timedelta(minutes=poll_minutes), SLOW_DOWN if slow_down else timedelta(0))
    factor: int = 2 ** max(failure_count - 1, 0)
    return min(base * factor, MAX_BACKOFF)


def is_due(connection: CGMConnection, now: datetime) -> bool:
    if not connection.enabled:
        return False
    if connection.retry_after is not None and now < connection.retry_after:
        return False
    if connection.last_poll_at is None:
        return True
    # A few seconds of slack so a 1-minute scheduler tick never skips a 1-minute poll.
    return now - connection.last_poll_at >= timedelta(minutes=connection.poll_minutes, seconds=-5)


def _librelinkup(
    connection: CGMConnection, runtime: CGMRuntime, now: datetime
) -> tuple[LibreLinkUpClient, LibreLinkUpSource]:
    if runtime.box is None:
        raise SecretKeyError("Set GBA_CGM_SECRET_KEY to use LibreLinkUp.")
    if not connection.email or not connection.password_encrypted:
        raise CGMAuthError("Enter the follower e-mail and password.")
    login = None
    if (
        connection.token_encrypted
        and connection.token_expires_at
        and connection.account_id is not None
        and not connection.reconnect_requested
    ):
        login = LluLogin(
            token=runtime.box.decrypt(connection.token_encrypted),
            expires_at=connection.token_expires_at,
            account_id=connection.account_id,
        )
    client = LibreLinkUpClient(
        runtime.http,
        connection.email,
        runtime.box.decrypt(connection.password_encrypted),
        server=connection.server,
        region=connection.region,
        version=connection.api_version or DEFAULT_VERSION,
        auto_accept_terms=connection.auto_accept_terms,
        login=login,
        clock=lambda: now,
    )
    connection.reconnect_requested = False
    return client, LibreLinkUpSource(client, connection.patient_id)


def _save_client_state(
    connection: CGMConnection, client: LibreLinkUpClient, box: SecretBox
) -> None:
    connection.region = client.region
    connection.api_version = client.version
    state = client.login_state
    if state is None:
        _reset_login(connection)
        connection.region = client.region
        return
    connection.token_encrypted = box.encrypt(state.token)
    connection.token_expires_at = state.expires_at
    connection.account_id = state.account_id


def _source(
    connection: CGMConnection, runtime: CGMRuntime, now: datetime
) -> tuple[CGMSource, LibreLinkUpClient | None]:
    if connection.source is CGMSourceKind.SIMULATOR:
        return SimulatorSource(runtime.trace(), clock=lambda: now), None
    client, source = _librelinkup(connection, runtime, now)
    return source, client


def poll_connection(
    session: Session, connection: CGMConnection, runtime: CGMRuntime, *, now: datetime
) -> int:
    """Fetch and store new readings for one connection. Errors are recorded, not raised."""
    connection.last_poll_at = now
    since = connection.last_reading_at or now - FIRST_POLL_HISTORY
    client: LibreLinkUpClient | None = None
    try:
        source, client = _source(connection, runtime, now)
        readings = source.fetch_readings(since)
        if isinstance(source, LibreLinkUpSource) and source.patient_id:
            connection.patient_id = source.patient_id
    except (CGMError, SecretKeyError) as error:
        slow_down = isinstance(error, CGMRateLimited | CGMAuthError)
        connection.failure_count += 1
        connection.retry_after = now + backoff(
            connection.failure_count, connection.poll_minutes, slow_down=slow_down
        )
        connection.last_error = str(error)
        # Only the class and the user id: the message never holds secrets, but stays short.
        log.warning("CGM poll failed for user %s: %s", connection.user_id, type(error).__name__)
        if isinstance(error, CGMAuthError) and client is not None:
            client.logout()
        added = 0
    else:
        added = store_readings(session, connection, readings)
        connection.last_success_at = now
        connection.last_error = None
        connection.failure_count = 0
        connection.retry_after = None
    finally:
        if client is not None and runtime.box is not None:
            _save_client_state(connection, client, runtime.box)
    session.flush()
    return added


def list_patients(
    session: Session, connection: CGMConnection, runtime: CGMRuntime, *, now: datetime
) -> list[LluPatient]:
    """Log in and list the people the follower account follows (for the settings page)."""
    client, _ = _librelinkup(connection, runtime, now)
    try:
        return client.patients()
    finally:
        assert runtime.box is not None
        _save_client_state(connection, client, runtime.box)
        session.flush()


# ---------- alerts ----------

# No glucose value in the text: it is pushed to the lock screen (ADR 0013). The live view
# shows the value.
ALERT_TEXT = {
    GlucoseAlertKind.LOW: ("Low glucose", "Treat the low now and recheck in 15 minutes."),
    GlucoseAlertKind.FALLING_FAST: (
        "Glucose falling fast",
        "Your glucose is dropping quickly. Check it and be ready to treat a low.",
    ),
    GlucoseAlertKind.HIGH: (
        "High glucose",
        "Above your target range. If it stays high, check for ketones and follow your "
        "sick-day plan.",
    ),
    GlucoseAlertKind.STALE: (
        "No new CGM readings",
        "Nothing new for 15 minutes. Check the sensor, the phone and the Libre app.",
    ),
}


def _latest(session: Session, connection: CGMConnection) -> Latest | None:
    reading = GlucoseRepository(session).latest_from(
        connection.user_id, SOURCE_OF[connection.source]
    )
    if reading is None:
        return None
    return Latest(reading.measured_at, reading.value_mgdl, reading.trend)


def check_alert(
    session: Session, connection: CGMConnection, settings: UserSettings, *, now: datetime
) -> Notification | None:
    """Add a notification if a live alert is due; remember the episode either way."""
    if not feature_flags(settings.delivery_mode, settings.monitoring_mode).live_alerts:
        return None
    if connection.last_reading_at is None:
        return None  # never had data: the settings page shows the problem instead
    latest = _latest(session, connection)
    kind = classify(
        latest, low_mgdl=settings.target_low_mgdl, high_mgdl=settings.target_high_mgdl, now=now
    )
    if kind is None:
        connection.alert_kind = None
        connection.alert_sent_at = None
        return None
    quiet = in_quiet_hours(now, quiet_hours_for(settings), ZoneInfo(settings.timezone))
    if not should_send(
        kind,
        previous=connection.alert_kind,
        previous_sent_at=connection.alert_sent_at,
        now=now,
        quiet=quiet,
    ):
        return None
    title, body = ALERT_TEXT[kind]
    notification = NotificationRepository(session).add(
        Notification(
            user_id=connection.user_id,
            title=title,
            body=body,
            created_at=now,
        )
    )
    connection.alert_kind = kind
    connection.alert_sent_at = now
    return notification


def poll_due(session: Session, runtime: CGMRuntime, *, now: datetime) -> list[Notification]:
    """Poll every connection that is due and return the alerts it raised."""
    created = []
    for connection in CGMConnectionRepository(session).enabled():
        settings = connection.user.settings
        if (
            settings is None
            or not feature_flags(settings.delivery_mode, settings.monitoring_mode).cgm_import
        ):
            continue
        if is_due(connection, now):
            poll_connection(session, connection, runtime, now=now)
        notification = check_alert(session, connection, settings, now=now)
        if notification is not None:
            created.append(notification)
    session.flush()
    return created


# ---------- live view ----------


@dataclass(frozen=True, slots=True)
class LiveStatus:
    connection: CGMConnection | None
    latest: GlucoseReading | None
    stale: bool
    recent: Sequence[GlucoseReading]


def live_status(session: Session, user: User, *, now: datetime, hours: int = 3) -> LiveStatus:
    """The newest CGM value, whether it is stale, and the last few hours for the sparkline."""
    connection = get_connection(session, user)
    if connection is None:
        return LiveStatus(None, None, True, [])
    repository = GlucoseRepository(session)
    source = SOURCE_OF[connection.source]
    latest = repository.latest_from(user.id, source)
    recent = [
        r
        for r in repository.between(
            user.id, now - timedelta(hours=hours), now + timedelta(minutes=5)
        )
        if r.source is source
    ]
    stale = is_stale(latest.measured_at if latest else None, now)
    return LiveStatus(connection, latest, stale, recent)
