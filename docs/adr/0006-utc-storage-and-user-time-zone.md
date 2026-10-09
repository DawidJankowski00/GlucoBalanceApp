# 0006. Store times in UTC, read and show them in the user's time zone

- Status: accepted
- Date: 2026-10-09

## Context

Stage 3 adds manual logging. A reading typed as "14:30" means 14:30 where the user is, while the database stores timezone-aware UTC times (ADR 0002). Daily charts need to know where "today" starts, and the glucose form guesses a tag (fasting, bedtime, night) from the time of day. Until now the app had no idea which time zone the user lives in.

## Decision

- Add a `timezone` setting: an IANA name such as `Europe/Warsaw`, stored on `user_settings` (default `UTC`) and changed through `apply_settings`, so every change is in the settings log.
- The onboarding wizard fills it from the browser (`Intl.DateTimeFormat().resolvedOptions().timeZone`) in a hidden field. An unknown or missing value falls back to `UTC`, which the user can correct on the settings page.
- Forms send wall-clock time (`datetime-local`, no zone). `web/log_forms.py` reads it in the user's zone and converts to UTC, so services and repositories only ever see UTC.
- Use Python's `zoneinfo` with the `tzdata` package as a dependency, because Windows has no system time zone database.
- Daylight saving gaps and repeats are resolved by `zoneinfo`'s default (`fold=0`): an ambiguous 02:30 on the autumn change is read as the first one.

## Consequences

- Readings keep their true moment when the user travels; only the display changes with the setting.
- One more setting to validate and log; tests cover summer and winter offsets.
- A wrong browser time zone gives wrong local times until the user fixes the setting.

## Alternatives considered

- **Store local time:** breaks ordering across daylight saving changes and travel.
- **Read the zone from the browser on every request:** no setting to manage, but server-side work (charts, later reminders and reports) has no browser to ask.
- **A fixed UTC offset:** wrong for half the year wherever daylight saving applies.
