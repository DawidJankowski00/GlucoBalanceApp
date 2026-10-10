# 0020. Security pass, synthetic demo accounts, data export and deletion

- Status: accepted
- Date: 2026-10-10

## Context

Stage 11 makes the app safe to put on the public internet as a demo, and gives a real user the two basic data rights: take everything out, and delete everything. The demo must be understandable in two minutes without signing up, must never hold real health data, and must run on a free tier with no paid database.

## Decision

- **CSRF protection by fetch metadata, not form tokens** (`security.CrossSiteGuard`). Every state-changing request (anything but GET, HEAD, OPTIONS) is refused with 403 when the browser's `Sec-Fetch-Site` header says it came from another site, or, for older browsers that do not send it, when the `Origin` header names a different host (or is `null`). Browsers set both headers themselves and a page on another site cannot forge them. Requests with neither (curl, test clients) carry no ambient login cookie, so they are no CSRF risk. Together with the `SameSite=Lax` session cookie (ADR 0004) this covers form posts, HTMX requests and `fetch` alike, without touching the 45 forms in the templates.
- **Rate limits in memory** (`security.RateLimiter`, a sliding window per key). Login: 30 attempts per 5 minutes per address and 8 per 15 minutes per email (a successful login clears the email count; a blocked attempt is not counted, so waiting always works). Sign-up: 10 per hour per address. Assistant: 30 questions per 10 minutes per user, which caps LLM spend. Over the limit, login and sign-up answer 429 with a plain message.
- **Proxy addresses only when trusted** (`GBA_TRUST_PROXY`). Behind Render or nginx the caller's address is in `X-Forwarded-For`; anywhere else that header is attacker-controlled, so it is ignored unless the setting is on.
- **Security headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, a `Permissions-Policy` that turns off camera, microphone and location, and a partial `Content-Security-Policy` (`frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`). HSTS in production.
- **Dependency audit and secrets scan in CI.** A `security` job exports the locked runtime dependencies and runs `pip-audit` on them (also weekly on a schedule, so new advisories show up without a push), and runs gitleaks over the whole git history.
- **Export is generic** (`data_export.collect`). It walks every table with a `user_id` column, so later tables are exported without changes. JSON keeps one list per table; the CSV download is a zip with one file per table and the spreadsheet-formula guard from the logbook. Secrets are left out: the password hash, the encrypted CGM password and token, and the push subscription table.
- **Deletion relies on the database.** Every user-owned foreign key already has `ON DELETE CASCADE` (SQLite gets `PRAGMA foreign_keys=ON`), so deleting the `users` row removes everything. The user retypes their email and password first. A test checks that no row of any kind is left.
- **Synthetic demo accounts** (`demo_data.py`). A small deterministic model (meal bumps, delayed insulin dips, an under-dosed breakfast, occasional night lows, a slow random walk) builds three weeks for a pump + CGM user and a pens + glucometer user in under a second, with no optional libraries. Both patterns the Stage 7 detectors look for appear in it. With `GBA_DEMO_MODE=true` the login page offers both as one-click logins, a banner says the data is synthetic and shared, the accounts cannot be deleted, and both are rebuilt at every start.
- **Free-tier deployment on Render with SQLite** (`render.yaml`). Since the demo is rebuilt at every start, nothing needs to survive a restart, so a file in `/tmp` replaces a paid (or 30-day free) PostgreSQL.

## Consequences

- The in-memory limiter counts per process. With several workers each has its own count; a shared store (Redis) would be needed then. The demo runs one process.
- The CSP does not restrict scripts yet: the Tailwind CDN script and two small inline scripts would need hashes or self-hosting first. The directives that hold today are on.
- Demo visitors share two accounts and can see each other's test entries until the next restart. The banner says so, and nothing real can be entered without a real account.
- The pens demo user has no password, so it cannot be logged into except through the demo buttons, and only while demo mode is on.

## Alternatives considered

- **Synchronizer tokens in every form** (for example `starlette-csrf`): the classic approach, but it means a hidden field in every form, a header for HTMX and JavaScript to copy it, and every existing test changed. Fetch metadata gives the same protection for every browser that supports SameSite cookies.
- **slowapi or a Redis limiter:** more features, another dependency; the three limits here fit in 60 lines and are tested with a fake clock.
- **Soft delete:** keeps data the user asked to remove. Real deletion is simpler and is what the user expects.
- **simglucose for the demo:** realistic but about 12 seconds per simulated day and an optional dependency that does not install on every Python. Kept for `python -m glucobalance.seed`.
