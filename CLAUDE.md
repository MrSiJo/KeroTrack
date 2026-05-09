# Working in this repo

## Security contract — non-negotiable

These guarantees are pinned by `backend/tests/api/test_security_invariants.py`
and enforced by the `.pre-commit-config.yaml` hooks. If a change you're making
collides with one of them, the right move is almost always to adjust the
change, not the contract.

### Endpoints
- Every new `/api/*` route requires authentication. The only exempt paths
  are listed in `backend/kerotrack/api/auth_middleware.py::EXEMPT_PATHS` —
  do not extend that set without explicit user sign-off.
- Mutating verbs (`POST`/`PUT`/`PATCH`/`DELETE`) on authenticated routes are
  CSRF-checked by `api/csrf.py::CSRFMiddleware`. The frontend sends the token
  via `X-CSRF-Token`. Pre-flight + login routes are the only legitimate
  exemptions; anything else needs the token.
- `/api/setup` is one-shot. The race-safe enforcement lives in
  `services/auth_service.py::bootstrap_user`. A second successful setup is a
  bug, not a feature — even if usernames or payloads differ.

### Auth + secrets
- Passwords are hashed with Argon2id via `security/crypto.py`. Don't
  introduce plaintext comparisons or alternative hashes.
- Password policy minimum is `MIN_PASSWORD_LENGTH = 12` in
  `services/auth_service.py`. The Pydantic bodies in
  `api/routes/auth.py` mirror this with `min_length=12` on `setup` and
  `change-password` (login is intentionally `min_length=1` to let legacy
  short passwords still authenticate for rotation).
- `APP_SECRET_KEY` lives only in `.env`. It must be ≥32 chars and not a
  placeholder; `bootstrap.py::Bootstrap._validate_secret_key` enforces this.
  Never commit `.env`. Never log the key. Never read it from any other
  source.
- Other operational secrets (MQTT password, Apprise URLs) live in the
  `settings` table with `is_secret=True` so they redact on read and in the
  audit log. New secret-bearing settings must set this flag.

### Cookies + transport
- The session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` when
  `SESSION_COOKIE_SECURE=true` (default). The deployment terminates TLS at
  nginx-proxy-manager; backend traffic from NPM is HTTP but the cookie's
  `Secure` flag still applies to the browser↔NPM hop. Tests opt out by
  setting `SESSION_COOKIE_SECURE=false`.

### Rate limiting
- `slowapi` rate-limits `POST /api/setup` and `POST /api/auth/login` at
  `5/minute` per remote IP. Wired in `api/rate_limit.py` and registered in
  `main.py`. Honours `X-Forwarded-For` from NPM via uvicorn's standard proxy
  header handling. Tests disable with `app.state.limiter.enabled = False`.

### Outbound HTTP / SSRF
- The price scraper (`prices/scraper.py`) and Apprise notifier reach URLs
  that come from settings. Any new feature that fetches a user-supplied URL
  must apply scheme validation (`http`/`https` only) at minimum, and an
  allowlist where feasible. Don't proxy arbitrary URLs through the backend.

### Database access
- All ORM access is parameter-bound. The one f-string SQL in
  `migration/v1_to_v2.py` is a CLI-only path against a hardcoded table set
  and is annotated `# nosec B608  # noqa: S608`. Don't add others.

## Pre-commit

Install once:

```bash
pre-commit install
```

What runs on every commit:
- **gitleaks** — scans the diff for accidentally-committed secrets
- **bandit** — Python security linter against `backend/kerotrack`
- **ruff** with the `S` ruleset (flake8-bandit equivalent)
- **forbid-environment-ips** — blocks RFC 1918 IPv4 literals being
  committed (use the `settings` table for deployment-specific addresses)

Run them all on demand:

```bash
pre-commit run --all-files
```

The `security-invariants` test suite is wired as a manual-stage hook so
it doesn't depend on pre-commit's isolated env (which would need every
backend dep installed). Run it from the active venv before merging
significant changes:

```bash
python -m pytest backend/tests/api/test_security_invariants.py -q
# or:
pre-commit run --hook-stage manual security-invariants
```

## Deploy ritual

After backend or frontend changes: commit → push → `docker compose up` on
the deploy host (set via the developer's local Docker context) → `curl
/api/health` to verify. Required for every change that ships. The exact
host address lives in the developer's local config, not in the repo.

## Tests

```bash
cd backend && python -m pytest          # 286+ tests, ~50s
python -m pytest tests/api/test_security_invariants.py   # ~7s, security only
```
