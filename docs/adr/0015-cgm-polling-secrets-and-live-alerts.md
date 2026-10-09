# 0015. CGM polling with backoff, encrypted follower secrets, and one alert per episode

- Status: accepted
- Date: 2026-10-09

## Context

Readings must flow in without the user doing anything, the follower password must be stored somewhere the scheduler can use it, and live alerts must reach the phone without repeating on every poll.

## Decision

- **One CGM job in the existing scheduler.** `poll-cgm` runs every `GBA_CGM_TICK_SECONDS` (60) and polls each enabled connection whose own interval (1 to 5 minutes, default 5) has passed. It uses the same database job store as the reminders job (ADR 0012).
- **Idempotent import.** Readings are inserted only if their (user, source, time) is new, which the unique key on `glucose_readings` also enforces. A poll asks for readings after the newest stored one; the first poll takes the last 12 hours. Values outside 40 to 500 mg/dL (a Libre sensor's LO and HI) are skipped. LibreLinkUp readings are stored as `cgm`, simulator readings as `simulated`.
- **Backoff.** After a failure the next try waits the poll interval, doubling with each failure in a row, capped at one hour. After a 429 or a refused login it waits at least 5 minutes, because retrying fast is what gets an account blocked. The error message is saved on the connection and shown on the settings and live pages.
- **Token reuse.** The LibreLinkUp token and its expiry are saved and reused until they expire, so the account logs in rarely. "Reconnect" forces a new login on the next poll, like GlucoDataHandler's switch.
- **Encrypted secrets.** The follower password and the token are encrypted with Fernet (symmetric, authenticated encryption from the `cryptography` package) using `GBA_CGM_SECRET_KEY`. Without a key the app runs but refuses to save a password. The password is never shown again, logged or put in an error message; tests check the log.
- **Stale data.** No new reading for more than 15 minutes is stale. The live view greys the value, hides the trend arrow and says not to dose from it.
- **Live alerts are episodes.** The newest reading is classified as stale, low (below the user's low target), falling fast, high (above the high target) or fine, in that order. An alert is sent when an episode starts and repeated only after 15 minutes (low), 30 minutes (falling fast), 1 hour (stale) or 2 hours (high). Low and falling fast ignore quiet hours; high and stale wait for them to end. Alerts go through the notification centre and Web Push (ADR 0013), so the text holds no glucose value.
- **Only CGM users** are polled and alerted; switching to glucometer stops both without deleting the connection.

## Consequences

- With a 1-minute tick a 1-minute interval works; shorter intervals are not offered, to respect the server.
- A lost key makes the stored password unreadable; the user is asked to enter it again.
- The alert thresholds are the user's target range, not separate alarm levels. Separate urgent-low and alarm settings can be added later.

## Alternatives considered

- **A separate worker process:** more moving parts for one user's data.
- **Storing the password in plain text or in the environment:** plain text leaks with a database copy; the environment cannot hold one password per user.
- **An alert on every poll while out of range:** quickly becomes noise and gets turned off.
