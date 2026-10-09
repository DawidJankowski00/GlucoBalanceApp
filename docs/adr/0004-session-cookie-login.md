# 0004. Signed session cookie for login, Argon2 for passwords

- Status: accepted
- Date: 2026-10-09

## Context

Stage 2 adds accounts. The UI is server-rendered (FastAPI, Jinja2, HTMX), so the browser is the only client. The app holds health data, so a stolen database or cookie should reveal as little as possible.

## Decision

- **Login state is a signed session cookie** (Starlette `SessionMiddleware`, `itsdangerous` signing) that holds only the user id. The key is `GBA_SECRET_KEY`; the app refuses to start in production without a private one. The cookie is `SameSite=Lax`, `Secure` in production, and expires after 14 days. The session is cleared and recreated on login.
- **Passwords are hashed with Argon2id** (`argon2-cffi` defaults), with a minimum length of 10 characters. Unknown emails still cost one hash check, so response time does not reveal which emails exist.
- **Forms are plain HTML posts** (with `hx-boost` for smooth page changes), parsed with `python-multipart`.

## Consequences

- No token storage or refresh logic in the browser; logging out is just clearing the cookie.
- The cookie is signed, not encrypted, so it must never hold more than the user id.
- A signed cookie cannot be revoked server-side before it expires. Rotating `GBA_SECRET_KEY` logs everyone out.
- CSRF beyond `SameSite=Lax` (tokens on forms) is planned for the Stage 11 security pass.

## Alternatives considered

- **JWT:** suits a separate mobile or SPA client; here it adds token handling and no benefit, and is harder to revoke.
- **Server-side session table:** revocable, but more code and a database read per request; revisit if revocation becomes a requirement.
