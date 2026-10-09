"""LibreLinkUp: reading FreeStyle Libre values through Abbott's follower service.

LibreLinkUp is the app Abbott made for family members who follow someone's glucose. This
client logs in as such a follower, the way GlucoDataHandler and nightscout-librelink-up do
(their code was used to check the endpoints, headers and replies). The interface is not
official and may change; see ADR 0014.

The flow:

1. ``POST /llu/auth/login`` with e-mail and password. The reply is one of:
   - a redirect to a regional server (``data.redirect`` and ``data.region``): log in there;
   - ``status 2``: wrong e-mail or password;
   - ``status 4``: a step is pending, such as new terms of use (``tou``) or a token
     confirmation (``pp``). Accept it with ``POST /auth/continue/<type>`` if allowed;
   - an ``authTicket`` with the token and its expiry, plus the follower's user id.
2. ``GET /llu/connections`` lists the people this account follows (the patients).
3. ``GET /llu/connections/<patientId>/graph`` gives the latest value with its trend arrow
   and the last 12 hours of values.

Every request carries the ``product`` and ``version`` headers the official app sends and,
after login, ``Authorization: Bearer <token>`` and ``Account-Id`` (the SHA-256 of the user
id). The token is kept and reused until it expires (``LluLogin``), because logging in on
every poll is what makes the server answer "429 Too Many Requests".

Nothing here logs the password, the token or a reply body.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from glucobalance.cgm.base import CGMAuthError, CGMError, CGMRateLimited, CGMReading
from glucobalance.models import Trend

log = logging.getLogger(__name__)

DEFAULT_VERSION = "4.17.0"
SERVERS = {"io": "Default (.io)", "ru": "Russia (.ru)"}
TIMEOUT_SECONDS = 20.0
_TIMESTAMP_FORMAT = "%m/%d/%Y %I:%M:%S %p"
# LibreLinkUp TrendArrow: 1 falling fast ... 5 rising fast.
_TRENDS = {
    1: Trend.FALLING_FAST,
    2: Trend.FALLING,
    3: Trend.STEADY,
    4: Trend.RISING,
    5: Trend.RISING_FAST,
}
_TERMS_STEP = "tou"
_TOKEN_STEP = "pp"
_MAX_STEPS = 4


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LluLogin:
    """A cached login: reuse ``token`` until ``expires_at``."""

    token: str
    expires_at: datetime
    account_id: str


@dataclass(frozen=True, slots=True)
class LluPatient:
    patient_id: str
    name: str


def parse_timestamp(raw: str) -> datetime:
    """Parse LibreLinkUp's ``FactoryTimestamp`` ("10/9/2026 6:21:08 PM", in UTC)."""
    return datetime.strptime(raw, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def _reading(item: dict[str, Any]) -> CGMReading | None:
    try:
        measured_at = parse_timestamp(str(item["FactoryTimestamp"]))
        value = round(float(item["ValueInMgPerDl"]))
    except (KeyError, TypeError, ValueError):
        return None
    if value <= 0:
        return None
    arrow = item.get("TrendArrow")
    trend = _TRENDS.get(arrow) if isinstance(arrow, int) else None
    return CGMReading(measured_at=measured_at, value_mgdl=value, trend=trend)


class LibreLinkUpClient:
    """A small synchronous client. Pass in the ``httpx.Client`` so tests can replay replies."""

    def __init__(
        self,
        http: httpx.Client,
        email: str,
        password: str,
        *,
        server: str = "io",
        region: str | None = None,
        version: str = DEFAULT_VERSION,
        auto_accept_terms: bool = True,
        login: LluLogin | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if server not in SERVERS:
            raise ValueError(f"unknown LibreLinkUp server {server!r}")
        self._http = http
        self._email = email
        self._password = password
        self._server = server
        self.region = region
        self.version = version
        self._auto_accept_terms = auto_accept_terms
        self.login_state = login
        self._clock = clock

    def __repr__(self) -> str:
        return f"LibreLinkUpClient(server={self._server!r}, region={self.region!r})"

    # ---------- HTTP ----------

    def _url(self, path: str) -> str:
        host = f"api-{self.region}" if self.region else "api"
        return f"https://{host}.libreview.{self._server}{path}"

    def _headers(self, token: str | None, account_id: str | None) -> dict[str, str]:
        headers = {
            "product": "llu.android",
            "version": self.version,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "cache-control": "no-cache",
        }
        if account_id:
            headers["Account-Id"] = hashlib.sha256(account_id.encode()).hexdigest()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        account_id: str | None = None,
        body: dict[str, str] | None = None,
        version_retry: bool = True,
    ) -> dict[str, Any]:
        try:
            response = self._http.request(
                method,
                self._url(path),
                headers=self._headers(token, account_id),
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise CGMError("Could not reach LibreLinkUp.") from exc
        if response.status_code == 429:
            raise CGMRateLimited("LibreLinkUp asked us to slow down (too many requests).")
        if response.status_code == 401:
            raise CGMAuthError("LibreLinkUp did not accept the saved login.")
        if response.status_code == 403 and version_retry:
            minimum = _json(response).get("data", {})
            if isinstance(minimum, dict) and isinstance(minimum.get("minimumVersion"), str):
                # The server wants a newer app version; GlucoDataHandler retries with it.
                self.version = minimum["minimumVersion"]
                log.info("LibreLinkUp asked for app version %s", self.version)
                return self._request(
                    method,
                    path,
                    token=token,
                    account_id=account_id,
                    body=body,
                    version_retry=False,
                )
        if response.status_code >= 400:
            raise CGMError(f"LibreLinkUp answered with HTTP {response.status_code}.")
        return _json(response)

    # ---------- login ----------

    def _login_from(self, data: dict[str, Any]) -> LluLogin:
        ticket = data.get("authTicket") or {}
        token = ticket.get("token")
        expires = ticket.get("expires")
        user = data.get("user") or {}
        if not isinstance(token, str) or not token or not isinstance(expires, int | float):
            raise CGMError("LibreLinkUp's login reply had no token.")
        account_id = str(
            user.get("id") or (self.login_state.account_id if self.login_state else "")
        )
        return LluLogin(
            token=token,
            expires_at=datetime.fromtimestamp(expires, UTC),
            account_id=account_id,
        )

    def _handle_step(self, payload: dict[str, Any], done: set[str]) -> dict[str, Any]:
        """Status 4: accept a pending step (if allowed) and return the next reply."""
        data = payload.get("data") or {}
        step = (data.get("step") or {}).get("type")
        ticket = (data.get("authTicket") or {}).get("token")
        allowed = step == _TOKEN_STEP or (step == _TERMS_STEP and self._auto_accept_terms)
        if not isinstance(step, str) or not isinstance(ticket, str) or step in done:
            raise CGMAuthError(
                "LibreLinkUp needs an action in its app. Log in to the LibreLinkUp app with the "
                "follower account and complete the steps shown there."
            )
        if not allowed:
            raise CGMAuthError(
                "LibreLinkUp has new terms of use. Accept them in the LibreLinkUp app, or turn "
                "on automatic acceptance here."
            )
        done.add(step)
        log.info("Accepting LibreLinkUp step %r", step)
        return self._request("POST", f"/auth/continue/{step}", token=ticket)

    def login(self) -> LluLogin:
        """Log in now (following a regional redirect and accepting allowed steps)."""
        payload = self._request(
            "POST", "/llu/auth/login", body={"email": self._email, "password": self._password}
        )
        done: set[str] = set()
        for _ in range(_MAX_STEPS):
            status = payload.get("status")
            data = payload.get("data") or {}
            if status == 2:
                raise CGMAuthError("LibreLinkUp refused the e-mail or password.")
            if status == 4:
                payload = self._handle_step(payload, done)
                continue
            if status not in (0, None):
                raise CGMError(f"LibreLinkUp login failed (status {status}).")
            if isinstance(data, dict) and data.get("redirect"):
                region = data.get("region")
                if not isinstance(region, str) or not region.isalnum() or region == self.region:
                    raise CGMError("LibreLinkUp sent an invalid regional redirect.")
                self.region = region
                log.info("LibreLinkUp redirected the login to region %r", region)
                return self.login()
            self.login_state = self._login_from(data)
            return self.login_state
        raise CGMError("LibreLinkUp asked for too many login steps.")

    def logout(self) -> None:
        """Forget the cached token so the next request logs in again."""
        self.login_state = None

    def _valid_login(self) -> LluLogin:
        state = self.login_state
        if state is None or state.expires_at <= self._clock():
            return self.login()
        return state

    def _get(self, path: str) -> dict[str, Any]:
        """An authenticated GET; if the token was revoked, log in once more and retry."""
        state = self._valid_login()
        try:
            return self._checked(
                self._request("GET", path, token=state.token, account_id=state.account_id)
            )
        except CGMAuthError:
            state = self.login()
            return self._checked(
                self._request("GET", path, token=state.token, account_id=state.account_id)
            )

    @staticmethod
    def _checked(payload: dict[str, Any]) -> dict[str, Any]:
        status = payload.get("status")
        if status not in (0, None):
            raise CGMAuthError(f"LibreLinkUp refused the request (status {status}).")
        return payload

    # ---------- data ----------

    def patients(self) -> list[LluPatient]:
        """The people this follower account follows."""
        data = self._get("/llu/connections").get("data")
        if not isinstance(data, list):
            raise CGMError("LibreLinkUp's connection list was not understood.")
        patients = []
        for item in data:
            if isinstance(item, dict) and item.get("patientId"):
                name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
                patients.append(LluPatient(str(item["patientId"]), name or str(item["patientId"])))
        return patients

    def graph(self, patient_id: str) -> list[CGMReading]:
        """The current value (with trend) and the last 12 hours, oldest first."""
        if not patient_id.replace("-", "").isalnum():
            raise ValueError("invalid patient id")
        data = self._get(f"/llu/connections/{patient_id}/graph").get("data")
        if not isinstance(data, dict):
            raise CGMError("LibreLinkUp's glucose data was not understood.")
        items: list[dict[str, Any]] = [
            i for i in data.get("graphData") or [] if isinstance(i, dict)
        ]
        current = (data.get("connection") or {}).get("glucoseMeasurement")
        if isinstance(current, dict):
            items.append(current)
        by_time: dict[datetime, CGMReading] = {}
        for item in items:
            reading = _reading(item)
            if reading is not None:
                # The current value comes last and carries the trend, so it wins a tie.
                by_time[reading.measured_at] = reading
        return [by_time[t] for t in sorted(by_time)]


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise CGMError("LibreLinkUp sent a reply that is not JSON.") from None
    if not isinstance(payload, dict):
        raise CGMError("LibreLinkUp sent an unexpected reply.")
    return payload


class LibreLinkUpSource:
    """The ``CGMSource`` adapter: picks the patient and filters the graph by time."""

    def __init__(self, client: LibreLinkUpClient, patient_id: str | None = None) -> None:
        self.client = client
        self.patient_id = patient_id

    def fetch_readings(self, since: datetime) -> Sequence[CGMReading]:
        if self.patient_id is None:
            patients = self.client.patients()
            if not patients:
                raise CGMError(
                    "This LibreLinkUp account follows nobody yet. Share from the Libre app and "
                    "accept the invitation in the LibreLinkUp app."
                )
            self.patient_id = patients[0].patient_id
        return [r for r in self.client.graph(self.patient_id) if r.measured_at > since]
