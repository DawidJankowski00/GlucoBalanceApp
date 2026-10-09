# 0014. LibreLinkUp behind a CGM source interface, with a simulator for demos and tests

- Status: accepted
- Date: 2026-10-09

## Context

The owner wears a FreeStyle Libre sensor. Abbott offers no public API for third-party apps. The practical route, used by GlucoDataHandler, nightscout-librelink-up and pylibrelinkup, is to log in to LibreLinkUp (Abbott's app for family members who follow someone) as a follower and read the same JSON the official app reads. Tests, CI and the future public demo must never reach Abbott's servers.

## Decision

- **One interface.** The app knows only `CGMSource.fetch_readings(since)`, which returns `CGMReading` values (UTC time, mg/dL, optional trend). Errors are `CGMError`, `CGMAuthError` and `CGMRateLimited`. Nothing outside `glucobalance.cgm` knows about LibreLinkUp, so Nightscout or another source can be added as one more adapter.
- **Two adapters.** `SimulatorSource` replays a one-day trace (simglucose when the optional `sim` group is installed, a built-in curve otherwise) on a 5-minute grid tied to the real clock, so the same moment always gives the same value. `LibreLinkUpSource` wraps `LibreLinkUpClient`.
- **The client follows GlucoDataHandler.** Endpoints, headers and replies were checked against `LibreLinkSourceTask.kt`: `POST /llu/auth/login`, the regional redirect (`api-<region>.libreview.io`), `status 2` for a wrong password, `status 4` steps accepted with `POST /auth/continue/<tou|pp>`, `GET /llu/connections`, `GET /llu/connections/<patientId>/graph`. Headers `product: llu.android`, `version`, and after login `Authorization: Bearer` and `Account-Id` (SHA-256 of the user id). A 403 naming a `minimumVersion` is retried once with that version, which is then saved.
- **The settings match GlucoDataHandler's screen:** enable, automatic acceptance of new terms (default on, as there), e-mail, password, server (`.io` or `.ru`), patient when several are followed, and reconnect.
- **httpx, synchronous.** The scheduler runs jobs in a thread, so a plain `httpx.Client` is simpler than async. The client is passed in, which lets tests replace the network.
- **Tests replay recorded replies with respx.** The JSON fixtures in `tests/fixtures/librelinkup/` copy the reply shapes with every id, name, token and serial number made up.

## Risks

- **Unofficial interface.** Abbott can change or block it at any time, and can change the minimum app version it accepts.
- **Encrypted v5 interface.** Abbott is moving LibreLinkUp to encrypted communication. GlucoDataHandler warns that when the old interface is switched off it will likely stop working, with no technical solution in sight. The same applies here. The settings page shows this warning.
- **Terms of service.** Using LibreLinkUp from a third-party program may not be allowed by Abbott's terms. Automatic acceptance of new terms accepts them on the user's behalf; the setting explains this and can be turned off.
- **Safety.** Imported values can be late, missing or wrong. The app treats data older than 15 minutes as stale, says so on the live view and does not base suggestions on it (design rule 4).

## Consequences

- If LibreLinkUp stops working, only `cgm/librelinkup.py` is affected; manual logging, the simulator and everything built on readings keep working.
- The respx tests prove the client handles the recorded shapes, not that Abbott's server still sends them. A real check needs the owner's follower account.

## Alternatives considered

- **pylibrelinkup as a dependency:** small and maintained, but it adds models we would translate anyway and hides the HTTP details that the owner wants to understand. Its code was used as a second reference.
- **Nightscout as the only source:** needs a separate server; it can be added later as another adapter.
- **Reading the phone's Libre app directly (like xDrip or Juggluco):** needs native Android code.
