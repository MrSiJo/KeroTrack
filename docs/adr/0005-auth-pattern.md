# ADR-0005: Single-user auth — argon2id + sessions + CSRF

**Status:** Accepted
**Date:** 2026-04-25
**Plan:** [`docs/plans/2026-04-25-v2-redesign.md`](../plans/2026-04-25-v2-redesign.md) §6 (auth subsection)
**Supersedes:** the "no auth in v2.0" line in the original spec §2.8

## Context

KeroTrack v1 had no auth — the dashboard sat on a private LAN. The v2 spec
originally deferred auth to v2.1 with a `RequireAuthMiddleware` slot
reserved. The operator has since asked for proper auth so v2 can be
exposed via a reverse proxy without leaving the API world-readable.

Two viable patterns were on the table:

- **Cookie sessions.** Starlette `SessionMiddleware` with an HTTP-only
  signed cookie, `argon2-cffi` for password hashing, CSRF middleware on
  mutating verbs, first-time `/setup` flow that bootstraps the single
  user and stores `APP_SECRET_KEY`-derived material.
- **JWT bearer tokens.** `bcrypt` + `passlib`, bearer header. Older
  pattern; common in stateless multi-tenant APIs.

The session pattern is the better fit for a single-user SPA on a private
network: cookies are SameSite-protected, free logout via `session.clear()`,
no revocation list to manage, and the frontend never has to handle a token
explicitly.

## Decision

KeroTrack v2 uses the **session-cookie** auth pattern:

- **Hashing:** `argon2-cffi`'s `PasswordHasher`. Default Argon2id parameters.
- **Sessions:** Starlette `SessionMiddleware` signed with `APP_SECRET_KEY` (32-byte random
  hex). HTTP-only cookie, `same_site=lax`. `Secure` flag toggled by
  `SESSION_COOKIE_SECURE` (default true; deployment terminates TLS at
  nginx-proxy-manager).
- **CSRF:** Custom middleware that requires `X-CSRF-Token` on `POST/PUT/PATCH/DELETE` for
  authenticated `/api/*` requests. Token issued on login, recoverable from `/api/auth/me`,
  stored in the session.
- **Auth gate:** Custom `RequireAuthMiddleware` returning `401 auth_required` for any
  `/api/*` request that isn't in the exempt set. Exempt: `/api/health`,
  `/api/setup/status`, `/api/setup`, `/api/auth/login`, `/api/auth/logout`.
- **Setup flow:** On first boot the DB has no user. The frontend calls
  `GET /api/setup/status` → `{needs_setup: true}` and renders the Setup page. `POST /api/setup`
  with `{username, password}` creates the user. Subsequent boots skip Setup and go to Login.
- **Single user.** The DB stores at most one user row; v2 is a single-operator app. The
  `users` table is structurally extensible (could grow a `roles` column, etc.) but the
  service refuses to create a second user.
- **Rate limiting.** `slowapi` enforces 5 attempts/minute per remote IP on
  `/api/setup` and `/api/auth/login` to blunt credential stuffing.

### Storage

A new `users` table:

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

User credentials live in their own table — *not* in `settings` — because the password
hash is not a "tunable runtime config", it's identity. This keeps `settings` clean and
keeps the `setting_changes` audit log free of password churn.

### Frontend

SvelteKit gets:

- `lib/stores/auth.ts` — current user, `needsSetup`, `csrfToken`.
- `routes/login/+page.svelte`, `routes/setup/+page.svelte`.
- Layout-level guard in `routes/+layout.svelte`: while `loading`, render a spinner; if
  `needsSetup`, redirect to `/setup`; if no `user`, redirect to `/login`; else render the
  app.
- `lib/api.ts` — fetch wrapper sets `credentials: "include"` and adds `X-CSRF-Token` for
  mutating verbs. On 401, clears the auth store and falls back to the login page.

## Consequences

- A login screen on every fresh deploy. First-time deploys land on `/setup`.
- `APP_SECRET_KEY` is now a load-bearing bootstrap env var (alongside `DATABASE_URL`,
  `TZ`, etc.). Lost key = invalidated sessions but no data loss.
- The MQTT ingest task and the scheduler are unaffected — they don't sit behind the auth
  middleware. KeroTrack-display continues to work because it's an MQTT consumer, not an
  HTTP client.
- Dependencies added: `argon2-cffi`, `itsdangerous` (transitively via Starlette
  `SessionMiddleware`), `cryptography` (already required for `Fernet` if/when we add
  encrypted secrets later), `slowapi` (rate limiting).
- One slot reserved for HA / Home Assistant integration if that ever calls the v2 API
  directly: a long-lived API token check could be added as a second auth backend without
  touching the session flow. Out of scope for v2.0.

## Alternatives considered

- **JWT bearer tokens.** Rejected — bearer tokens leak more easily on a
  LAN web app and there's no SPA reason to prefer them over session
  cookies. The session model also gives us free logout
  (`session.clear()`) without revocation lists.
- **HTTP basic auth at nginx.** Tempting for simplicity but blocks the SPA from showing a
  branded login page and a `/setup` flow, and forces us to manage `htpasswd` on the host
  outside the container.
- **No auth (original v2.0 plan).** Decision overturned — the operator
  asked for proper auth so v2 can sit behind a reverse proxy without
  exposing an unauthenticated API.
