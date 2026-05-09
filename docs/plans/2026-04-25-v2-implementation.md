# KeroTrack v2 — Phased Implementation Plan

**Date:** 2026-04-25
**Status:** Approved for execution
**Spec:** [`2026-04-25-v2-redesign.md`](./2026-04-25-v2-redesign.md) — read first
**Design language:** [`ADR-0004`](../adr/0004-frontend-design-language.md)
**Auth pattern:** [`ADR-0005`](../adr/0005-auth-pattern.md) — single-user, session-cookie

**Phases:** 0 → 1 → 2 → **2.5 (auth)** → 3 → 4 → 5 → 6 → 7 → 8. Phase 2.5 (single-user
session-cookie auth) is added per the operator's request and supersedes
the original spec's "no auth in v2.0" stance.

> **Address placeholders.** Hosts are written as `<v1-host>`,
> `<docker-host>`, `<mqtt-broker>` etc. **These are placeholders —
> substitute the real hostnames or IPs of your own environment.** They
> vary by deployment; the v2 runtime makes no assumption about any
> particular subnet. All operational settings (broker host, scrape URLs,
> notifier endpoints) are stored in the `settings` table in the
> database, not the codebase.

---

## How this plan is run

This plan executes as **nine phases**, each ending with green tests and a deploy. Phases are either **sequential** (single-agent execution because work is tightly coupled or load-bearing) or **parallel** (multi-agent fan-out via `superpowers:dispatching-parallel-agents`).

### TDD discipline (every phase, no exceptions)

Each phase follows this loop, enforced by `superpowers:test-driven-development`:

1. **Read the spec section** for the phase. Note exit criteria.
2. **Write tests against the spec, watch them fail.** Tests come from the spec, not from the implementation. If you can't write the test, you don't understand the requirement yet — go back to the spec.
3. **Implement the minimum to make tests pass.** No speculative features, no abstractions for "future flexibility". The test is the contract.
4. **Refactor under green tests.** Cleanups, naming, extraction. Tests stay green throughout.
5. **Run the full suite** (not just the new tests) to catch regressions. Use `superpowers:verification-before-completion` before claiming done.
6. **Commit, push, deploy, verify on the host.** See §15 of the spec.
7. **Mark the phase status** in this file (`Status: Done · sha=<commit>`) and commit that too.

### Sub-agent dispatch

Each phase declares its agent strategy:

- **Sequential phase** — one `general-purpose` agent runs the phase end-to-end. The main session reviews the work before the commit.
- **Parallel phase** — the main session uses `superpowers:dispatching-parallel-agents` to fan out independent workstreams across multiple `general-purpose` agents (run in a single message with multiple `Agent` tool calls). Each agent is briefed with: phase ID, sub-stream ID, exact files it owns, exact files it must NOT touch, the spec sections that define its contract, and the test files it must write first. Agents work on disjoint file sets so merges are clean.
- **Code review** — every phase invokes `superpowers:code-reviewer` after implementation, before the commit. Material findings get fixed, then re-reviewed.

### Commit + deploy ritual (§15 of the spec)

```bash
# 1. Tests green
pytest backend/tests -q
npm --prefix frontend test

# 2. Commit straight to main, push
git add -A
git commit -m "<phase-N> <one-line summary>"
git push

# 3. Deploy to the docker host (context already configured)
docker compose --env-file .env up -d --build

# 4. Verify
curl -fsS http://<docker-host>:9176/api/health
# (and any phase-specific verification step listed in the phase exit criteria)
```

If a deploy goes sideways: `git revert HEAD && git push && docker compose --env-file .env up -d --build`. Volumes survive the redeploy.

### What the MVP is

**Feature parity with v1**, end-to-end, on the SvelteKit frontend, configured via the DB-backed settings, with the v1 SQLite DB migrated cleanly. Plus **single-user login** (ADR-0005). That bar is what each phase contributes to. New behaviour beyond parity (forecast fan, calendar heatmap, scheduler reload-on-settings-change, audit log, SSE, login/setup) is in scope because it's already designed; **multi-tank, multi-user/role auth, API tokens, TLS, Postgres, and encrypted secrets are not.**

### Source of truth for the v1 port

The local v1 repo at `C:/code/KeroTrack` is the canonical source for the port. The deployed v1 at `root@<v1-host>:/opt/KeroTrack/` lags behind it (verified 2026-04-25 — 4 of 5 core files differ). Phase 3 ports come from the local repo; the deployed system is only used as a *data source* (its SQLite DB and YAML config) and as the *cutover target* (it gets replaced).

### Open decision: SQLite provision

§9.0 of the spec has the recommended approach: sanitised fixture in repo + full local copy in `legacy/` (gitignored) + production cutover via SSH snapshot. **This plan assumes that choice.** Anywhere a fixture is referenced, it's the sanitised one. If you'd rather skip the sanitisation step, only Phase 6's `scripts/build-fixture.py` deliverable changes.

---

## Phase 0 — Repo scaffold and guardrails

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~0.5 day
**Depends on:** none
**Blocks:** all subsequent phases

### Objective

Empty but runnable v2 project. `pytest` collects zero tests cleanly. SvelteKit dev server starts. Docker images build (with no application code yet). The deploy ritual proves out end-to-end against a stub `/api/health` that returns `{"status": "scaffold"}`.

### Files created

```
backend/
  pyproject.toml               # kerotrack package, deps: fastapi uvicorn aiosqlite sqlalchemy aiomqtt apscheduler apprise httpx pyyaml pydantic pydantic-settings cron-converter
  Dockerfile
  kerotrack/__init__.py
  kerotrack/main.py            # FastAPI(title="KeroTrack v2"); GET /api/health → {"status":"scaffold"}
  tests/__init__.py
  tests/conftest.py
frontend/
  package.json
  Dockerfile
  nginx-frontend.conf
  svelte.config.js
  vite.config.ts
  tailwind.config.ts
  tsconfig.json
  src/app.html
  src/routes/+layout.svelte
  src/routes/+page.svelte      # placeholder "KeroTrack v2 — scaffold"
  tests/.gitkeep
compose.yaml
.env.example
.dockerignore
pytest.ini
```

### Tests written first

- `backend/tests/test_scaffold.py` — `from kerotrack.main import app` succeeds; `app.title == "KeroTrack v2"`; `client.get("/api/health").status_code == 200` returns `{"status":"scaffold"}`.

### Implementation steps

1. Write the failing test (`test_scaffold.py`).
2. `backend/pyproject.toml` and `kerotrack/main.py` minimal enough to make the test pass.
3. `frontend/` SvelteKit init via `npm create svelte@latest` flow — adapter-static, TypeScript, Tailwind.
4. `compose.yaml` per spec §8.1.
5. Dockerfiles per spec §8.2 / §8.3.
6. `.env.example` per spec §8.4.

### Exit criteria

- `pytest backend/tests -q` → 1 passed.
- `npm --prefix frontend run build` → succeeds.
- `docker compose --env-file .env up -d --build` from the dev workstation against the docker-host context → both containers healthy.
- `curl http://<docker-host>:9176/api/health` → `{"status":"scaffold"}`.
- `curl http://<docker-host>:9177` → SvelteKit placeholder page.

### Commit

`Phase 0 · scaffold backend, frontend, compose, dockerfiles`

---

## Phase 1 — Settings foundation

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~1 day
**Depends on:** Phase 0
**Blocks:** every other phase (settings is load-bearing — scheduler, MQTT, prices, notifier all read through it)

### Objective

A complete settings system: catalogue, seed, get/set/list/reset/subscribe, audit log, API surface, secret redaction. Driven entirely by tests against the spec's catalogue (§5.2) and contract (§5.4).

### Files created

```
backend/kerotrack/models/setting.py
backend/kerotrack/models/setting_change.py
backend/kerotrack/settings/schema.py        # the typed catalogue, every key from spec §5.2
backend/kerotrack/settings/seeds.py         # default values, idempotent insert
backend/kerotrack/settings/service.py       # get/set/all/reset/subscribe + cache
backend/kerotrack/api/routes/settings.py    # GET/PUT /api/settings, /schema, /reset, /changes
backend/tests/unit/test_settings_schema.py
backend/tests/unit/test_settings_service.py
backend/tests/api/test_settings_api.py
```

### Tests written first

- **Schema** — every key in §5.2 is present in the catalogue; types and defaults match the spec; secret keys are flagged.
- **Service** — type round-trip per `value_type` (`string`, `int`, `float`, `bool`, `cron`, `json`, `secret`); `set` validates type and rejects unknown keys; cache invalidated on set; `subscribe` fires on change with `(key, old, new)`; cron-typed keys reject invalid expressions.
- **Audit** — every `set` writes to `setting_changes`; secrets are redacted to `***` in old/new columns.
- **API** — `GET /api/settings` returns grouped, types coerced, secrets `********`; `PUT /api/settings/{key}` round-trips; bulk `PUT /api/settings` saves the diff; `GET /api/settings/schema` returns the catalogue; unknown key on `PUT` returns 400 `unknown_setting`; type mismatch returns 422 with field-level reasons.

### Implementation order

1. Models and schema catalogue.
2. Idempotent seed (only inserts missing keys; never overwrites operator changes).
3. Service with cache and subscribers.
4. API routes.
5. Audit log on every `set`.

### Exit criteria

- All tests green.
- `curl -X GET http://<docker-host>:9176/api/settings/schema` returns the full catalogue.
- `curl -X PUT http://<docker-host>:9176/api/settings/tank.capacity_l -d '{"value": 1500}'` updates and reads back as 1500.
- A secret key (`mqtt.password`) returns `********` on read but stores correctly when `PUT`.

### Commit

`Phase 1 · DB-backed settings · catalogue, service, API, audit`

---

## Phase 2 — DB engine, lifespan, health

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~0.5 day
**Depends on:** Phase 1
**Blocks:** Phases 3, 4, 5, 6

### Objective

Async SQLAlchemy engine with WAL pragma. Idempotent schema bootstrap covering every v1 table (`readings`, `analysis_results`, `refill_data`, `refill_periods`, `hdd_data`, `energy_metrics`, `cost_analysis`) plus the v2 additions (`settings`, `setting_changes`). FastAPI lifespan wires the engine, applies the schema, seeds settings, exposes a real `/api/health` reporting DB status and last reading age.

### Files created / modified

```
backend/kerotrack/bootstrap.py             # pydantic-settings, reads .env (DATABASE_URL, TZ, LOG_LEVEL, ports)
backend/kerotrack/db.py                    # async engine factory, WAL pragma, session helper
backend/kerotrack/db_migrate.py            # ensure_schema() — every table from spec §3.4
backend/kerotrack/models/reading.py        # + analysis_result.py, refill.py, refill_period.py, hdd.py, energy_metric.py, cost_analysis.py
backend/kerotrack/api/routes/health.py
backend/kerotrack/main.py                  # lifespan: bootstrap → engine → schema → seed settings → health
backend/tests/unit/test_db_engine.py
backend/tests/integration/test_lifespan.py
backend/tests/api/test_health.py
```

### Tests written first

- WAL is set on connect (PRAGMA journal_mode returns `wal`).
- `ensure_schema` is idempotent: running it twice on an empty DB and once-then-once-more produces the same schema.
- Lifespan opens the engine, applies the schema, seeds settings, and tears down cleanly on shutdown.
- `GET /api/health` returns `{status: ok, db: ok, mqtt_connected: false, last_reading_at: null, age_seconds: null, scheduler_running: false}` in the empty-DB case.

### Exit criteria

- All tests green.
- `docker compose up` healthy with `/api/health` reporting `db: ok` against the named volume's fresh DB.
- WAL files (`-wal`, `-shm`) appear in the volume next to the DB.

### Commit

`Phase 2 · async engine, schema bootstrap, lifespan, /api/health`

---

## Phase 2.5 — Auth foundation (single-user, session-cookie)

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~0.75 day
**Depends on:** Phase 2 (engine + schema)
**Blocks:** Phase 5 (API surface — auth gate must exist before routes go live), Phase 7 (frontend needs login/setup pages)
**ADR:** [`0005`](../adr/0005-auth-pattern.md)

### Objective

Wire in the session-cookie auth pattern: argon2id password hashing, Starlette
`SessionMiddleware`, custom `RequireAuthMiddleware` and `CSRFMiddleware`, first-time
setup flow, login/logout/me routes. Single-user — the service refuses to create a
second user. No password churn pollutes `setting_changes`; credentials live in their
own `users` table.

### Files created / modified

```
backend/kerotrack/models/user.py
backend/kerotrack/security/__init__.py
backend/kerotrack/security/crypto.py            # argon2id hash_password / verify_password
backend/kerotrack/api/auth_middleware.py        # RequireAuthMiddleware + exempt set
backend/kerotrack/api/csrf.py                   # CSRFMiddleware + generate_csrf_token
backend/kerotrack/api/routes/auth.py            # /api/setup/status, /api/setup, /api/auth/{login,logout,me,change-password}
backend/kerotrack/services/auth_service.py      # bootstrap_user, get_user, is_setup_complete, change_password
backend/kerotrack/db_migrate.py                 # add `users` table (idempotent)
backend/kerotrack/bootstrap.py                  # add APP_SECRET_KEY validator (placeholder + length checks)
backend/kerotrack/main.py                       # wire SessionMiddleware → RequireAuth → CSRF
backend/pyproject.toml                          # + argon2-cffi, itsdangerous (transitive), cryptography
backend/tests/unit/test_crypto.py
backend/tests/unit/test_auth_service.py
backend/tests/api/test_setup_flow.py
backend/tests/api/test_auth_routes.py
backend/tests/api/test_auth_middleware.py
backend/tests/api/test_csrf_middleware.py
.env.example                                    # APP_SECRET_KEY=
```

### Tests written first

- **Crypto** — `hash_password` returns argon2id format; `verify_password` round-trips;
  bad password → `False`; malformed hash → `False` (not an exception).
- **Bootstrap validator** — empty / placeholder / short `APP_SECRET_KEY` raises at startup
  with a clear "generate one with `openssl rand -hex 32`" message.
- **Auth service** — `is_setup_complete` is `False` on empty DB, `True` after `bootstrap_user`;
  bootstrapping a second user raises `409 already_setup`.
- **Setup flow** — `GET /api/setup/status` works pre- and post-setup; `POST /api/setup`
  with valid body creates the user and returns `{username}`; second `POST` is `409`.
- **Login / me / logout** — successful login sets a session cookie and returns a
  `csrf_token`; `/api/auth/me` echoes the user and the same token; logout clears the
  session and subsequent calls 401.
- **Change password** — `POST /api/auth/change-password` with `{old_password, new_password}`
  verifies the old password, rehashes the new one, and writes back; subsequent login
  with the old password fails (`401`); login with the new one succeeds. Wrong old
  password returns `400 invalid_password` without leaking timing or which field was
  wrong. The route requires an authenticated session and a valid CSRF token.
- **Auth gate** — exempt paths return 2xx without a session; unexempt paths return
  `401 auth_required` without a session and the proper response with one.
- **CSRF** — `POST /api/settings/...` with a session but no `X-CSRF-Token` returns `403
  csrf_missing`; with the right token, `200`. `/api/setup` and `/api/auth/login` are
  CSRF-exempt (verified).
- **Middleware order** — Session → RequireAuth → CSRF, asserted by inserting a probe
  middleware that records dispatch order.

### Implementation order

1. `users` model and idempotent table creation in `db_migrate`.
2. `security/crypto.py` (4 tiny functions).
3. `services/auth_service.py` — single-user bootstrap, `verify_password` lookup.
4. `bootstrap.py` — add `APP_SECRET_KEY` field with placeholder + length validators.
5. Middlewares (`auth_middleware.py`, `csrf.py`) — straight ports.
6. Routes (`api/routes/auth.py`).
7. Wire into `main.py` lifespan in the load-bearing order documented in spec §6.6.

### Exit criteria

- All tests green.
- On the host: a fresh deploy with an empty volume answers `GET /api/setup/status` →
  `{"needs_setup": true}`. After `POST /api/setup` with `{"username": "admin", "password":
  "..."}`, `GET /api/setup/status` returns `{"needs_setup": false}`.
- `POST /api/auth/login` returns a session cookie + CSRF token; subsequent
  `PUT /api/settings/tank.capacity_l` with the cookie + `X-CSRF-Token` succeeds, without
  the token returns `403 csrf_missing`.
- `POST /api/auth/change-password` with the cookie + CSRF token rotates the password;
  the next login with the old credentials fails 401 and with the new one succeeds.
- The host stack still reports `mqtt_connected: false` because MQTT isn't wired yet (Phase 3),
  but `/api/health` is reachable without auth (it's exempt) and reports `db: ok`.

### Commit

`Phase 2.5 · single-user auth · argon2id, sessions, CSRF, setup/login/logout`

---

## Phase 3 — Data layer (parallel · 3 sub-agents)

**Status:** Pending
**Mode:** Parallel · 3 sub-agents dispatched in one message
**Effort:** ~2 days wall-clock with parallelism (≈2.5 days serial)
**Depends on:** Phase 2
**Blocks:** Phases 4, 5

### Objective

Three independent workstreams that share only the DB schema and settings service. They run in parallel with disjoint file sets.

### Sub-agents

#### 3a — Recalc port

**Owns:** `backend/kerotrack/ingest/recalc.py`, `backend/tests/unit/test_recalc.py`, `backend/tests/integration/test_recalc_pipeline.py`, `backend/tests/fixtures/watchman_sonic_payloads.json`.

**Does not touch:** anything outside `ingest/recalc.py` and its tests.

**Brief:** Port `oil_recalc.py` from the v1 repo (functions only — no module-level config load, no logging side-effects on import). Reads tank/boiler/analysis/detection settings via the settings service. Lock the output contract: feed canonical Watchman Sonic Advanced JSON in, assert the exact output schema (every key in spec §3.1) including `cost_to_fill` as a string. Temperature compensation, density correction, refill detection, leak detection, HDD all preserved.

#### 3b — Price scraper

**Owns:** `backend/kerotrack/prices/scraper.py`, `backend/kerotrack/prices/cache.py`, `backend/tests/unit/test_price_scraper.py`, `backend/tests/unit/test_price_cache.py`.

**Does not touch:** anything outside `prices/`.

**Brief:** Port the BoilerJuice + HomeFuelsDirect scrapers from the v1 `oil_recalc.py`. Per-source retry, stale-cache fallback when both fail. JSON cache at `/app/data/price_cache.json` (path from settings via `prices.cache_ttl_seconds`). Tests use `respx` to mock the scraper sites and prove the retry / fallback paths.

#### 3c — MQTT ingest + publish

**Owns:** `backend/kerotrack/ingest/mqtt.py`, `backend/kerotrack/publish/mqtt_publisher.py`, `backend/kerotrack/pubsub/bus.py`, `backend/tests/unit/test_mqtt_ingest.py`, `backend/tests/unit/test_mqtt_publisher.py`, `backend/tests/integration/test_mqtt_lifecycle.py`.

**Does not touch:** scheduler or analysis modules.

**Brief:** `aiomqtt`-based async subscriber/publisher. Subscriber consumes `mqtt.topic_readings`, calls `recalc.process()`, persists, publishes the v1-compatible level payload, fires `pubsub.publish("reading", row)`. Publisher exposes `publish_level`, `publish_analysis`, `publish_costanalysis` — each formatted to the v1 contract. Tests:
- Subscriber lifecycle starts/stops cleanly under FastAPI lifespan
- Settings change for `mqtt.*` triggers a reconnect
- `publish_level` produces *exactly* the v1 JSON (golden-path tests against fixture from KeroDisplay's perspective)
- pubsub bus delivers events to multiple async subscribers without leaks

### Integration after parallel work

Main session pulls the three branches together:

1. Wire `ingest.mqtt` into `main.py` lifespan as a `create_task` that gets cancelled on shutdown.
2. Run the full test suite to confirm no cross-stream regressions.
3. Code review.

### Exit criteria

- All three streams' tests green individually.
- Combined integration test: a fixture Watchman Sonic JSON published to a local mosquitto (or `aiomqtt.Server` test broker) ends up as a row in `readings`, an outbound publish on `oiltank/level`, and a `reading` event on the pubsub bus — with the published payload byte-for-byte matching the v1 fixture.
- On the docker host: with the live broker configured in settings, `/api/health` reports `mqtt_connected: true` and `last_reading_at` updates within `mqtt.broadcast_interval_minutes`.
- KeroTrack-display (the ESP32) on the same broker still updates — proves the wire contract is preserved.

### Commit

`Phase 3 · ingest pipeline · recalc, prices, MQTT subscribe/publish, pubsub`

---

## Phase 4 — Scheduled jobs (parallel · 3 sub-agents + scheduler integration)

**Status:** Pending
**Mode:** Parallel · 3 sub-agents then sequential integration
**Effort:** ~2 days
**Depends on:** Phases 2 (DB) and 3 (publisher exists for analysis to publish through)
**Blocks:** Phase 5 (admin endpoints), Phase 8

### Objective

Port the three scheduled scripts from v1 into modules called by APScheduler. Scheduler is settings-driven and reloads triggers when cron expressions change.

### Sub-agents

#### 4a — Consumption / analysis port

**Owns:** `backend/kerotrack/analysis/consumption.py`, `backend/tests/unit/test_consumption.py`, `backend/tests/integration/test_analysis_pipeline.py`.

**Brief:** Port `oil_analysis.py`. Reads from `readings`, writes to `analysis_results`, publishes to `oiltank/analysis` via `MqttPublisher`. Output JSON locked to spec §3.2 with a golden-path test. HDD-adjusted forecasts, days-to-empty, seasonal heating factor — all preserved.

#### 4b — Cost analysis port

**Owns:** `backend/kerotrack/analysis/cost.py`, `backend/tests/unit/test_cost_analysis.py`, `backend/tests/integration/test_cost_pipeline.py`.

**Brief:** Port `oil_cost_analysis.py` *and* migrate it off raw `yaml.safe_load` onto the settings service. Output JSON locked to `oiltank/costanalysis` contract (spec §3.3). The interactive CLI flags (`--add-refill`, `--list-refills`, `--delete-refill`, `--clear-refills`, `--import-historical`) become subcommands of `python -m kerotrack.cli`.

#### 4c — Notifier port

**Owns:** `backend/kerotrack/notifier/apprise_notifier.py`, `backend/tests/unit/test_notifier.py`.

**Brief:** Port `notifier.py`. Same Sun/first-Sun predicate. `notifications.apprise_urls` from settings. Refill-aware totals identical to v1. Exposes a `run(test_mode=False)` callable used by the scheduler and `/api/admin/jobs/notifier/run`.

### Integration step (sequential, main session)

**Owns:** `backend/kerotrack/scheduler/service.py`, `backend/kerotrack/scheduler/jobs.py`, `backend/tests/integration/test_scheduler.py`.

- APScheduler `AsyncIOScheduler` with TZ from bootstrap.
- Three jobs registered with cron triggers from settings (`schedule.analysis_cron`, `schedule.cost_analysis_cron`, `schedule.notifier_cron`).
- `coalesce=True`, `misfire_grace_time=3600`.
- `last_run_at` and `last_status` written into settings per job.
- Subscribed to `schedule.*` settings changes — rebuilds triggers without process restart.
- Wired into `main.py` lifespan.

### Exit criteria

- All tests green incl. scheduler reload-on-settings-change.
- On the host: `POST /api/admin/jobs/analysis/run` writes a new `analysis_results` row and publishes on `oiltank/analysis`.
- Manually changing `schedule.notifier_cron` via `PUT /api/settings/schedule.notifier_cron` reschedules the job within seconds (verified via scheduler logs).

### Commit

`Phase 4 · scheduled jobs · analysis, cost, notifier, APScheduler with live reload`

---

## Phase 5 — Full API surface

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~1.5 days
**Depends on:** Phases 1, 2, 3, 4
**Blocks:** Phase 7 (frontend needs the API)

### Objective

Every read endpoint the SvelteKit pages need, the SSE stream, the admin endpoints, the records edit/delete, refills POST. Typed responses (Pydantic models) shared with the frontend types via the spec's `lib/types/api.ts` (hand-mirrored or generated; pick at the start of the phase).

### Files created

```
backend/kerotrack/api/routes/status.py            # GET /api/status
backend/kerotrack/api/routes/readings.py          # GET, POST {date}, DELETE {date}
backend/kerotrack/api/routes/analysis.py          # GET /latest, /history
backend/kerotrack/api/routes/costs.py             # GET /summary, /periods
backend/kerotrack/api/routes/refills.py           # GET, POST
backend/kerotrack/api/routes/hdd.py
backend/kerotrack/api/routes/mqtt_feed.py
backend/kerotrack/api/routes/stream.py            # SSE
backend/kerotrack/api/routes/admin.py             # POST /jobs/{name}/run, /reload-settings
backend/kerotrack/api/errors.py
backend/kerotrack/api/deps.py
backend/tests/api/test_*.py                       # one per route module
```

### Tests written first

- Per route: golden-path response shape, edge cases (empty DB, pagination boundaries, filters), validation errors return 422 with field-level reasons.
- SSE: subscriber receives `reading` events when pubsub publishes.
- Admin: `POST /api/admin/jobs/notifier/run` with `{"test": true}` triggers a notifier dry-run.

### Exit criteria

- All tests green.
- On the host: every documented endpoint reachable via `curl`.
- Live SSE: `curl -N http://<docker-host>:9176/api/stream` streams events as MQTT messages arrive.

### Commit

`Phase 5 · API surface · status, readings, analysis, costs, refills, SSE, admin`

---

## Phase 6 — Migration CLI + fixture builder

**Status:** Pending
**Mode:** Sequential · single agent
**Effort:** ~1 day
**Depends on:** Phases 1, 2

### Objective

`python -m kerotrack.cli migrate-v1 --src-db PATH --src-config PATH [--dry-run] [--report PATH] [--force]` end-to-end. Plus `scripts/build-fixture.py` that generates `backend/tests/fixtures/v1_sample.db` from a real v1 DB with sanitisation applied.

### Files created

```
backend/kerotrack/cli.py                          # argparse subcommands: migrate-v1, dump-settings, set-setting, run-job
backend/kerotrack/migration/v1_to_v2.py           # the actual migrator
backend/kerotrack/migration/yaml_mapping.py       # spec §9.3 mapping table, machine-readable
scripts/build-fixture.py                          # one-shot fixture generator with redaction
backend/tests/fixtures/v1_sample.db               # generated, committed
backend/tests/integration/test_migration.py
backend/tests/unit/test_yaml_mapping.py
```

### Tests written first

- **Schema parity** — running the migrator against the sanitised fixture produces row counts matching the source per table.
- **YAML coverage** — every leaf in a sample v1 `config.yaml` lands in a `settings` row with the right type, secrets flagged.
- **Idempotency** — second run is a no-op; `--force` re-runs cleanly.
- **`--dry-run`** — produces the same diff report as a wet run, leaves no rows.
- **Tolerant** — v1 DB with only `readings` populated migrates without erroring; report flags empty source tables.
- **Fixture builder** — `build-fixture.py` against the local v1 DB produces a smaller DB with the redactions applied.

### Developer prerequisites

Once Phase 6 starts, copy your v1 DB and config into `C:/code/KeroTrack-v2/legacy/` (gitignored):

```
legacy/
  KeroTrack_data.db
  config.yaml
```

Then run `python scripts/build-fixture.py` once to generate `backend/tests/fixtures/v1_sample.db`. The fixture stays in the repo; the legacy/ copy stays out.

### Exit criteria

- All tests green.
- On the host (manual rehearsal, ahead of cutover): `docker compose run --rm -v $PWD/legacy:/app/legacy:ro backend python -m kerotrack.cli migrate-v1 --src-db /app/legacy/KeroTrack_data.db --src-config /app/legacy/config.yaml --dry-run --report /app/data/dry-run.json` produces a clean diff report against your real DB.

### Commit

`Phase 6 · v1→v2 migration CLI, sanitised fixture, dry-run + report`

---

## Phase 7 — Frontend (parallel · scaffold then 7 pages in two waves)

**Status:** Pending
**Mode:** Sequential 7a, then **parallel waves** 7b–7h via `dispatching-parallel-agents`
**Effort:** ~7.5 days wall-clock with parallelism
**Depends on:** Phase 5 (API contract finalised)

### 7a — Scaffold + auth UI (sequential)

**Owns:** entire `frontend/` tree, Tailwind config, ECharts theme registration, typed API client, layout chrome, theme store, sidebar, **the login + setup pages and the auth guard.**

**Brief:** Implement the design language locked in ADR-0004. Register the
`kerotrack-dark` ECharts theme once at app boot. `lib/api.ts` is a typed fetch client
matching Phase 5 routes — sends `credentials: "include"`, attaches `X-CSRF-Token` for
mutating verbs, and calls a registered `onUnauthorised` callback on 401.
`lib/stores/{auth,liveStatus,settings,theme}.ts` per spec §7.2 — `auth.ts`
orchestrates the auth state (boot calls `/api/setup/status`, then `/api/auth/me` if setup;
exposes `user`, `needsSetup`, `csrfToken`, `login`, `logout`, `refresh`).
`routes/+layout.svelte` is the auth guard: while loading shows a spinner, if
`needsSetup` redirects to `/setup`, if no `user` redirects to `/login`, else renders the
chrome (sidebar, header, theme toggle). `routes/login/+page.svelte` and
`routes/setup/+page.svelte` use the ADR-0004 palette. `Sidebar.svelte`, `KeyboardHints.svelte`, `ThemeToggle.svelte`. SSE
wiring via `EventSource` against `/api/stream`. **No analytics/dashboard content yet**
— only chrome, login/setup, and the empty page shells with route stubs.

**Tests:**
- vitest for the typed client (mocked fetch, CSRF header behaviour, 401 callback)
- stores (theme persistence, auth setup-then-login flow, liveStatus SSE parsing)
- sidebar keyboard nav
- layout guard logic (mock the auth store, assert redirects)

**Commit:** `Phase 7a · frontend scaffold · chrome, auth pages, ECharts theme, typed API client, stores`

### Waves 7b–7h — pages in parallel

Two waves, dispatched together in one message each. Each agent owns exactly its page and its test files; no shared writes.

**Wave 1 (3 agents in parallel):**

- **7b — Dashboard** (`src/routes/+page.svelte` + `lib/components/{TankSilhouette,StatusPills,Sparkline,StatCard}.svelte`)
- **7c — Records** (`src/routes/records/+page.svelte` + `[date]/+page.svelte` + `lib/components/DataTable.svelte`)
- **7d — Settings** (`src/routes/settings/+page.svelte` + `lib/components/{SettingsForm,SettingField,ChangePasswordForm}.svelte`, cron-next-fires preview via `cron-converter`, **a "Change password" section that POSTs to `/api/auth/change-password`** — see ADR-0005. Old password + new password + confirm; clears the form and shows a toast on 200; surfaces `400 invalid_password` inline.)

**Wave 2 (3 agents in parallel, after Wave 1 lands):**

- **7e — Trends** (`src/routes/trends/+page.svelte` + `lib/components/{LineChart,BarChart,ScatterChart,CalendarHeatmap}.svelte`)
- **7f — Forecast** (`src/routes/forecast/+page.svelte` + `lib/components/ForecastFan.svelte`)
- **7g — Costs** (`src/routes/costs/+page.svelte` + reuse of `LineChart`, `BarChart`, `DataTable`)

**Wave 3 (1 agent):**

- **7h — MQTT page** (`src/routes/mqtt/+page.svelte` + `lib/components/MqttFeed.svelte`)

### Tests per page

- vitest unit for any page-local logic (e.g. anomaly highlighting in DataTable)
- Playwright e2e for the golden-path interaction:
  - Dashboard renders against a fixed API mock and shows the tank at the right level
  - Records edits a row and the change reflects after reload
  - Settings saves a diff and reads it back
  - Settings → Change password rotates credentials; old password fails on next login, new one succeeds
  - Theme toggle persists across reload
  - Trends date range picker filters chart data

### Exit criteria (per wave)

- All wave tests green.
- Visual review against the approved mockup — the agent attaches a screenshot per page to the commit message; review must call out any deviation from ADR-0004 before merging.
- Deploy after each wave; manually verify each newly-landed page on the host.

### Commits

- `Phase 7a · frontend scaffold`
- `Phase 7b-d · dashboard, records, settings pages`
- `Phase 7e-g · trends, forecast, costs pages`
- `Phase 7h · MQTT page`

---

## Phase 8 — Cutover rehearsal and production migration (operator-triggered)

**Status:** Pending — **deferred until the operator stops the v1 LXC**
**Mode:** Sequential · operator-driven on the production host
**Effort:** ~0.5 day rehearsal + ~1 hour cutover window
**Depends on:** Phases 6 (migrator) and 7 (frontend MVP)

### What "ready for cutover" means in this plan

Phases 0–7 land an **empty-DB v2 deployment** with the session-cookie login flow on the
docker host. The operator can hit `http://<docker-host>:9177`, complete the first-time
`/setup`, log in, see all pages render against the empty DB, and confirm the auth flow
end-to-end. **No automated ingest happens** until the operator changes
`mqtt.broker` from `localhost` to the real broker via the Settings page (or until
cutover migrates the v1 settings).

This phase is the operator-driven follow-up:

1. Operator stops the v1 LXC (`<v1-host>`).
2. Operator runs the steps below to populate v2 with the snapshot.

The implementation agent does **not** stop the LXC, run the migration, or decommission v1
on the operator's behalf — those are explicit operator decisions. The agent has, by the
end of Phase 6, made `python -m kerotrack.cli migrate-v1` reliable and idempotent against
the local fixture and the local `legacy/` copy of the production DB.

### Objective

Production cutover from v1 → v2 with rollback rehearsed.

### Hosts (verified 2026-04-25)

- **v1 LXC**: `root@<v1-host>`, hostname `KeroTrack`. Runs `KeroTrack-MQTT.service` and `KeroTrack-Web.service` as system user `KeroTrack`. Cron entries: `/etc/cron.d/KeroTrack-Notifier` (Sun 08:00), `/etc/cron.weekly/KeroTrack-Analysis`, `/etc/cron.monthly/KeroTrack-CostAnalysis`.
- **Docker host**: `root@<docker-host>`. Runs v2 via `docker context use docker-host`.
- **MQTT broker** (shared): `<mqtt-broker>:1883`.

### Steps

1. **Rehearsal in dev.** With `legacy/` populated, run a full migration into a fresh container, hit every page in the dashboard, confirm KeroTrack-display still updates against the dev broker. Document any sharp edges.
2. **Snapshot v1 on the production host.**
   ```bash
   ssh root@<v1-host> "tar czf /root/kerotrack-v1-$(date +%F).tgz /opt/KeroTrack/data /opt/KeroTrack/config"
   scp root@<v1-host>:/root/kerotrack-v1-*.tgz root@<docker-host>:/root/
   ssh root@<docker-host> "mkdir -p /root/v1-snapshot && tar xzf /root/kerotrack-v1-*.tgz --strip-components=2 -C /root/v1-snapshot"
   ```
3. **Stop v1.** `ssh root@<v1-host> "systemctl stop KeroTrack-Web KeroTrack-MQTT"`. Disable the cron entries: `ssh root@<v1-host> "rm /etc/cron.d/KeroTrack-Notifier /etc/cron.weekly/KeroTrack-Analysis /etc/cron.monthly/KeroTrack-CostAnalysis"`.
4. **Migrate.** From the dev workstation with the docker-host context active:
   ```bash
   docker compose run --rm \
     -v /root/v1-snapshot:/app/legacy:ro \
     backend python -m kerotrack.cli migrate-v1 \
       --src-db /app/legacy/KeroTrack_data.db \
       --src-config /app/legacy/config.yaml \
       --report /app/data/migration-report.json
   ```
5. **Inspect the report.** Sanity-check row counts (expect ~17 k readings, ~6.7 k analysis_results, 9 refill_periods, 0 actual_refill_costs as of last snapshot), "defaulted", and "ignored" lists.
6. **Bring up v2.** `docker compose --env-file .env up -d --build`.
7. **Verify.** `/api/health` shows `mqtt_connected: true` within one broadcast interval; trigger `POST /api/admin/jobs/notifier/run` with `{"test": true}` and confirm the Gotify notification arrives; visit each page and sanity-check; confirm KeroTrack-display still updates.
8. **Decommission.** On `<v1-host>`: `systemctl disable --now KeroTrack-Web KeroTrack-MQTT`, `rm /etc/systemd/system/KeroTrack-{Web,MQTT}.service`, `rm -rf /opt/KeroTrack`, `userdel KeroTrack`. Keep the snapshot tarball for 30 days. Optionally power off the LXC.

### Rollback procedure (rehearsed before cutover)

```bash
docker compose down            # on docker-host context (<docker-host>)
ssh root@<v1-host> "systemctl start KeroTrack-MQTT KeroTrack-Web"
# and re-create cron entries from the snapshot if step 3 removed them
```

v2 writes are isolated in the `kerotrack-data` named volume; v1 state is intact in `/opt/KeroTrack` on `<v1-host>`. Rollback window is **as long as v1 systemd services remain installed** — keep them in place for one full notifier cycle (1 week) post-cutover; only run step 8 (decommission) once that window expires cleanly.

### Exit criteria

- v2 is the canonical KeroTrack on the production host.
- KeroTrack-display still updates without configuration changes.
- HA sensors still update without configuration changes.
- v1 systemd units removed; `/opt/KeroTrack` archived to a tarball off-host.
- This file is updated to mark every phase `Status: Done` with the cutover commit SHA.

### Commit

`Phase 8 · production cutover complete · v1 archived`

---

## Risks during execution

These are the live risks to watch as phases execute. Each one is mitigated above; flagged here so they can't be forgotten.

| Risk | Mitigation owner | Phase |
|---|---|---|
| MQTT contract drift breaks KeroTrack-display | Phase 3c golden-path tests | 3 |
| Settings catalogue diverges from spec §5.2 | Phase 1 schema test enumerates the catalogue | 1 |
| Migrator merges silently into a non-empty v2 DB | Phase 6 `--force` guard + idempotency test | 6 |
| Phase 4 scheduler misfires on container downtime | `coalesce=True`, `misfire_grace_time=3600`, `last_run_at` stamps | 4 |
| Phase 7 visual drift from ADR-0004 | Per-wave visual review against the approved mockup | 7 |
| `aiomqtt` vs `paho` parity issues | Phase 3c integration test against a real test broker | 3 |
| SQLite WAL on Docker volume on Windows | Use named volume in production AND dev | 2 |
| Production cutover loses data | Snapshot tarball before stopping v1; v2 writes to separate volume | 8 |

---

## Phase status summary

| Phase | Status | Commit |
|---|---|---|
| 0 — Scaffold | Done | `6dd81e1` |
| 1 — Settings foundation | Done | `Phase 1` commit |
| 2 — DB engine, lifespan, health | Done | `Phase 2` commit |
| 2.5 — Auth foundation (single-user, session-cookie) | Done | `Phase 2.5` commit |
| 3 — Data layer (parallel) | Done | `Phase 3` commit (live MQTT wired in `42f7018`) |
| 4 — Scheduled jobs (parallel) | Done | `Phase 4` commit |
| 5 — API surface | Done | `Phase 5` commit |
| 6 — Migration CLI | Done | `Phase 6` commit |
| 7a — Frontend scaffold + auth UI | Done | `Phase 7` commit |
| 7b-d — Dashboard, Records, Settings (incl. change-password) | Done | `Phase 7` + dashboard fixes `a92ea5d` |
| 7e-g — Trends, Forecast, Costs | Done | ECharts visuals shipped in `627ecda`, chart-data fixes in `b0c0b17` |
| 7h — MQTT page | Done | live SSE wiring shipped in `627ecda` |
| 8 — Cutover (operator-driven) | Done | data migrated `2026-04-26`, v1 LXC powered off and left in place |
| §18 live shakedown | Done | trends/forecast clip + ONS rebuild + chart fixes (`e74d762`, `bc64d8a`, `cbf665c`, `60e02dc`, `b0c0b17`) |

Update this table after each phase's deploy + verification step.

---

## 16. Post-Phase-7 follow-up work (delivered 2026-04-26)

After the autonomous run completed Phases 0–7, the operator brought the
container into live service and a number of issues surfaced that needed
fixing before v1 could be retired. All of them are committed and deployed.

### 16.1 Phase 8 — production cutover (executed)

The plan deferred Phase 8 to the operator. In practice it was driven by
agent + operator together on `2026-04-26`:

1. **v1 snapshot pulled to local `legacy/`**:
   `scp root@<v1-host>:/opt/KeroTrack/data/{KeroTrack_data.db,historical_deliveries.txt} root@<v1-host>:/opt/KeroTrack/config/config.yaml legacy/`
2. **Files staged into the running backend container** via
   `docker cp legacy/KeroTrack_data.db kerotrack-api:/tmp/v1.db` etc.
3. **Migrator run with `--force`** against the deployed v2 stack:
   `docker exec kerotrack-api python -m kerotrack.cli migrate-v1
    --src-db /tmp/v1.db --src-config /tmp/v1.yaml
    --report /app/data/migration-report.json --force`
4. **Result**: 17,310 readings · 9 refill periods · 12 HDD rows · 11 cost
   analyses · 42 settings imported. 6,669 `analysis_results` rows skipped
   due to v1's NULL-PK quirk on `latest_reading_date` (data not lost — the
   scheduler's analysis run regenerates them clean). The single-user
   account created at first-time `/setup` was **not** touched by the
   migrator.
5. **Operator stopped the v1 LXC** at `<v1-host>`. KeroTrack-display +
   HA continue to read from the shared `<mqtt-broker>` broker without
   configuration changes.

**Cutover is complete.** Operator's call: the powered-off v1 LXC stays
as-is — no archive tarball, `userdel`, or unit cleanup is planned. v2
owns kerosene tracking from this point.

### 16.2 Live MQTT ingest (Phase 3c made real) — `42f7018`

Phase 3c shipped the recalc/publish/pubsub modules but left the aiomqtt
loop dormant. The post-cutover commit replaced the dormant publisher with
a real subscriber/publisher loop:

- `ingest/mqtt.MqttIngest.run()` connects with exponential backoff,
  subscribes to `mqtt.topic_readings`, and consumes messages through
  `handle_payload` → recalc → DB → publish → pubsub.
- Idle when `mqtt.broker == "localhost"` (the operator-safe default),
  reconnects on `mqtt.*` settings change via the on-change hook.
- `_AiomqttPublisherAdapter` keeps `app.state.publisher` stable across
  reconnects — analysis/cost jobs publish through the same handle.
- `app.state.mqtt.connected` is what `/api/health.mqtt_connected` reads.

YAML mapping fix (same commit): `migration/yaml_mapping.py` now picks the
RTL_433-shaped entry (the one whose `name` contains `RTL_433toMQTT`) for
`mqtt.topic_readings`. v1 stored the SUBSCRIBE topic differently from
the publish topics; the original mapping picked the publish topic by
mistake and ingested nothing.

### 16.3 Dashboard fixes — `a92ea5d`

Visual issues caught on first use:
- `TankSilhouette.svelte` rewritten with a real coloured fill
  (gradient, clipped to the rounded inner rect) at the live
  percentage; 25/50/75% tick marks; waterline; tone shifts
  amber<25% / red<15% per ADR-0004.
- 10-bar vertical gauge from the mockup added next to the tank,
  driven by `bars_remaining` (or derived from pct).
- `StatCard` got a `compact` mode to remove empty-space padding.
- Dashboard reorganised: tank hero owns the percentage; the duplicate
  "Percentage" card is gone; nine real stats now pack the grid;
  refill/leak/low-level alert pills shown inline only when active.

### 16.4 Notifier — rich Markdown format restored — `b06bdc1`

The Phase 4 stub sent a 3-line plain-text body. Ported verbatim from
v1's `notifier.py`:

- Refill-aware weekly + monthly usage maths (positive deltas as refills,
  negative accumulated as usage; clamped ≥ 0).
- Trend arrow logic (⬆️/⬇️/➖) with combined L / £ / % delta string.
- Markdown body with Tank Level / Weekly Usage / Trend / Est. Empty
  sections; refill notice line when weekly_refill_volume > 0; monthly
  block appended on first-Sunday or test mode.
- Gotify URLs auto-tagged `?format=markdown` so the body renders.
- `apprise.notify(..., body_format=NotifyFormat.MARKDOWN)`.

### 16.5 Live ingest — populate price + scope previous-reading lookup — `e51aa17`

Two regressions caught on the first real reading from the lilygo:

1. **`current_ppl`/`cost_used`/`cost_to_fill` collapsed to 0/"0.00"**
   because `RecalcContext.current_ppl` was never populated and ingest had
   no price source plumbed in. Added `prices/service.PriceService` — a
   long-lived async wrapper over the Phase 3 scraper + cache — and threaded
   `prices.current_ppl` into `MqttIngest` as a `price_provider`. Provider
   failure degrades gracefully to `0.00`, payload still ingested.

2. **`litres_used_since_last` collapsed to 0** because `_load_previous`
   matched rows AT or AFTER the new payload's timestamp (e.g. duplicates
   or already-migrated rows at the same minute). Now scopes the lookup to
   `WHERE date < new_date`.

### 16.6 Prices — BoilerJuice parser fix + YourNRG replacement — `3510614`

- **BoilerJuice parser** previously grabbed the first
  `<span class="font-weight-bold">` (the logo) and bailed. Now walks all
  bold spans, requires "per litre" in the text, sanity-bounds 30–500 ppl.
  Live page returned 106.95 ppl; new parser picks it up.
- **HomeFuelsDirect's domestic page is gone.** Replaced with **YourNRG**
  (`https://yournrg.co.uk/domestic/heating-oil-prices`). The page renders
  prices via JS, but the underlying Umbraco API
  `/Umbraco/Surface/InformationPageSurface/GetCurrentAveragePrices`
  returns clean JSON. New scraper hits that endpoint and returns
  500/750/1000 L prices; the 500 L value is the fallback headline that
  matches v1 semantics.
- Setting catalogue: `prices.homefuelsdirect_url` renamed to
  `prices.yournrg_url`. v1's `oil_prices.url` demoted to "ignored" by
  the migrator so operators on the dead URL get the working default.

### 16.7 DST/timezone correctness — `c4857fd`

v1 stored naive `'YYYY-MM-DD HH:MM:SS'` strings produced by
`datetime.now()` on a Europe/London LXC. v2 inadvertently switched to
`datetime.utcnow()` in ingest, analysis, and cost paths — the same
wall-clock string but interpreted as UTC, silently shifting every BST
reading by an hour and breaking age/diff maths.

Added `kerotrack/clock.py`: `local_now()` / `local_now_str()` /
`parse_local()` all key off `Bootstrap.tz` (default `Europe/London`).
On-disk representation unchanged — every delta calculation now respects
DST automatically. Sites switched off UTC: ingest payload normaliser,
analysis consumption, analysis cost, /api/health age computation, and
the notifier `now` default.

### 16.8 Test count

Backend: **238 tests passing** (up from 219 at end of Phase 7).
Frontend: **7 tests passing** (unchanged).

---

## 17. Backlog — DONE 2026-04-26

The original backlog is fully delivered. Five commits landed
end-to-end:

- A1 (`c75df92`) — analysis algorithm restoration
- A2-A5 (`68afffe`) — refill_periods writer, per-pair cost, HDD metrics, weighted averages
- A6-A8 (`1d0fd4f`) — status byte logging, refill CLI, lifespan asserts MQTT + prices
- B1-B5 (`a52b02f`) — light-mode palette, cron preview, schedule open, utcnow, retired key
- C1+C2 (`627ecda`) — Phase 7e-7h ECharts visuals + Playwright smoke wiring

Snapshot of what was originally outstanding, kept for the historical
record. Items marked **DONE** were delivered in the commit listed.

### A. Backend logic — DONE

#### A1. Analysis: hot-water baseline + heating clamps + bounded look-back

The Phase 4 port took shortcuts that work fine on migrated historical
data but produce misleading averages once v2 starts running its own
analysis on live readings. v1 (587 lines) had:

- A **hot-water baseline** `daily_hw_l ≈ 1.5–2 L/day` derived from
  `boiler.fuel_rate_l_per_h` × scheduled HW sessions/week ÷ 7. Used as a
  **floor** on per-day consumption when HDD=0. v2 has no floor — summer
  days with ~0.3 L/day are taken at face value, deflating
  `avg_daily_consumption_l` and ballooning `estimated_days_remaining`.
- A **bounded look-back window**: `lookback_days = min(60, max(30, days_since_refill))`.
  v2 averages over the full ~365-day post-refill window so summer's
  near-zero usage poisons the heating-season baseline.
- **Heating estimate blending**: `(heating_7d × 0.65) + (heating_long × 0.35)`,
  scaled by today_HDD/avg_7day_HDD (clamped 0.6–1.6), final result
  clamped to 0.5–15 L/day. v2 just does `avg_daily × seasonal_factor`
  with no clamps — mid-summer gets implausible heating numbers.
- A **monthly seasonal heating factor** table derived from real Nest
  hours data (78 in Jan, 21 in April, 0 in Jun/Jul/Aug). v2 buckets
  months into three coarse seasons (1.0/0.7/0.3); April resolves to
  0.7 when the empirical factor is 0.27 — overstates April heating ~3×.
- An **`estimated_days_remaining` cap** of 400 days when HDD>0, 700
  otherwise. v2 has no cap and can produce multi-thousand-day
  projections in summer.
- **Per-pair refill-aware walker** (`if used < -refill_threshold:
  continue; if used <= 0: continue`) for `total_consumption`. v2 uses a
  single first-vs-latest delta which is wrong if there's any sensor
  jitter or undetected spike inside the window.

**Recommendation**: restore the v1 algorithm. Same output keys, better
values. Estimate: ~150 lines added to `analysis/consumption.py`, plus
the per-pair walker helper. Tests need: HW-baseline floor on warm
days; clamps trigger above 15 L/day; bounded look-back during long
post-refill windows.

#### A2. Cost: refill_periods is never written by v2 (silent breakage)

`analysis/cost.compute()` only **reads** from `refill_periods`. The
v1 implementation's `analyze_costs_between_refills()` (in
`oil_cost_analysis.py`) detected refill events from
`actual_refill_costs` (preferred when present) or sensor-detected
refills (fallback), paired consecutive refills, walked the readings
between, and **wrote** a row per period back into `refill_periods`. v2
has none of that.

**Concrete consequence**: the 9 period rows that came across in the
Phase 8 migration are all that will ever exist. The next time the
sensor detects a refill, or the operator POSTs an actual refill cost
via `/api/refills`, no period row is generated. The Costs page and
the cost-analysis MQTT publish freeze on that 9-row dataset
indefinitely.

**Recommendation**: implement `_detect_periods()` and call it from
`run_cost_analysis` before `compute()`. Should:
- Find refill markers in `readings` (date, litres_remaining at refill)
- Pair consecutive refills into periods
- Walk readings inside each period for reading-based cost
  (`Σ consumption_pair × ppl_at_pair / 100`) — preferred over
  `total × average_ppl`
- Prefer `actual_refill_costs` invoiced amounts when matched to a
  refill date (within 24h tolerance, per v1)
- Upsert each period into `refill_periods`

Estimate: ~200 lines in `analysis/cost.py`. Output payload unchanged.

#### A3. Cost: per-period reading-based cost + actual-cost preference

Even before period generation lands, the existing rows would benefit
from the v1 cost-walker:
- v1's `calculate_cost_for_period()` weights every consumption pair by
  the PPL **at that time**, not the period average. Material when
  prices move within a period.
- v1 prefers `actual_refill_costs` (invoiced) over sensor-detected
  refills. v2 reads the table but only uses it to compute
  `percentage_with_actual_data`.

**Recommendation**: ride along with A2. Output payload unchanged
(same `latest_*` and historical-average keys), values become more
defensible.

#### A4. Cost: HDD cost metrics + energy efficiency recompute

v1's `calculate_hdd_cost_metrics`, `calculate_cost_metrics_with_efficiency`,
and `calculate_energy_metrics` derive `cost_per_hdd`,
`cost_per_useful_kwh`, `energy_efficiency` from real HDD + reading
data. v2 hard-codes
`energy_efficiency = boiler.efficiency_pct / 100` (the configured
nameplate, not measured) and reads `cost_per_hdd` flat from the
period row.

**Recommendation**: implement once A2 is in (the period generator
needs HDD + efficiency lookups anyway). Estimate: ~80 lines.

#### A5. Cost: leap-year days_in_month + weighted historical averages

v1: `days_in_month = days_in_year/12` (366/12 in leap years).
v2: hard-coded `× 30`. Off by ~1.5%. Trivial fix.

v1 weights historical averages by `total_days` per period; v2 takes a
flat mean across periods. Bigger periods should weigh more.

#### A6. Recalc: status byte decode (logging only, no payload change)

v1's `decode_status()` translated `192/128/144/152` into "Initial sync
/ Post-sync / Transitional / Normal" for log readability. v2 stores
the raw byte under `raw_flags` (correct on the wire) but loses
human-readable state in logs.

**Recommendation**: add the dict + a `logger.info()` call when a
non-Normal status arrives. Wire format unchanged.

#### A7. CLI: refill management subcommands

The Phase 6 plan called for `--add-refill`, `--list-refills`,
`--delete-refill`, `--clear-refills`, `--import-historical` as
subcommands of `python -m kerotrack.cli`. They were skipped to fit
the overnight scope. The `/api/refills` POST/DELETE routes cover the
basics, but the import-historical workflow (parse
`historical_deliveries.txt`) isn't reachable without the CLI.

**Recommendation**: implement after A2 lands. Each subcommand is
~20–40 lines wrapping the existing service calls.

#### A8. Test: lifespan should verify MQTT + PriceService

`tests/integration/test_lifespan.py` only asserts the engine + DB
come up. With the live MQTT loop and PriceService now part of the
lifespan, the test should verify they're on `app.state` and the
shutdown cleans them up. Trivial extension once A1–A4 stabilise.

### B. Cosmetic / UX — DONE

#### B1. Theme toggle is a visual no-op

The `theme` store flips state and the `<html>` `dark`/`light` class
toggles correctly, but `tailwind.config.ts` palette tokens
(`bg.page`, `bg.panel`, `text.*`, `border.*`) are hard-coded to the
dark values regardless of class. Light mode needs either CSS custom
properties that resolve differently under `:root.light` or palette
overrides scoped to `.light` selectors. **Dark must remain the
default per ADR-0004.**

#### B2. Settings: cron next-3-fires preview

`cron-converter` is on the dep list but the SettingField for
`cron`-typed values doesn't render the next-3-fires preview. Quick
client-side add.

#### B3. Settings: schedule accordion default-open

The `schedule` group is currently collapsed by default in
`routes/settings/+page.svelte`. Worth flipping to default-open since
the user actively edits these.

#### B4. `datetime.utcnow()` deprecation warnings

`prices/cache.py` and `prices/scraper.py` still use `utcnow()` for
cache freshness deltas. Correct semantically (UTC for relative
windows) but noisy on Python 3.13+. Migrate to
`datetime.now(timezone.utc)`.

#### B5. Stale `prices.homefuelsdirect_url` settings row

The catalogue rename to `prices.yournrg_url` left the old key in the
live DB (seed only inserts missing rows). `SettingsService.all()`
flags it `"stale": true`. Cleanup migration:
`DELETE FROM settings WHERE key = 'prices.homefuelsdirect_url'`.
Harmless until then.

### C. Deferred phase work — DONE

#### C1. Frontend Phase 7e–7h ECharts visuals

The Trends, Forecast, Costs and MQTT pages are data-driven stubs.
Still to land:
- **Trends** — dual-axis line (oil level + temperature in teal),
  daily-consumption bars with anomaly amber colouring, HDD scatter
  with trend line + R², calendar heatmap (year-at-a-glance).
- **Forecast** — fan chart (median + p25/p75 + p5/p95 envelopes),
  scenario table, two-segment doughnut for heating/hot-water split.
- **Costs** — ppl step-line history (constant between reads), bar
  chart + table for per-period costs, energy-efficiency bars.
- **MQTT page** — replace the 10-second polling refresh with a live
  SSE subscription for the in-flight feed flash effect.

Acceptance gate: visual review against ADR-0004. Best done **after**
A1–A4 land so the chart inputs are the corrected numbers.

#### C2. Playwright e2e wiring

Playwright is configured in `frontend/package.json` but never
executed (no headless browser overnight). Worth wiring into the
deploy ritual once C1 lands.

#### C3. Phase 8 housekeeping — closed

Data migrated 2026-04-26; v1 LXC powered off. Operator's decision:
no archive tarball, no `userdel`, no systemd/cron unit removal —
the powered-off LXC stays as-is. Cutover considered complete.

---

## 18. Post-backlog live shakedown (delivered 2026-04-26)

After the §17 backlog landed and v2 went into live service, a fresh
batch of issues surfaced from real data on the dashboard. All fixed +
deployed the same day. Listed in the order they happened.

### 18.1 Trends 90d/365d → 422 + Forecast horizon clip — `e74d762`

- `/api/readings` `limit` cap raised 2000→25000 (a year of broadcasts is
  ~17k rows; the page asked for 4 700 / 10 000 and got
  `Unprocessable Entity`).
- Forecast fan now clips horizon to `min(365, days_to_empty)` so the
  chart ends at the projected empty date instead of running off into a
  meaningless tail.
- Heating-vs-hot-water split section labels itself a "latest analysis
  snapshot" with the analysis timestamp (it's a point-in-time read,
  not a window).

### 18.2 A1 follow-up — `bc64d8a`

`avg_daily_consumption_l` was being fed by the per-pair `_usage_stats`
total. v1 actually uses a SIMPLE 7-day delta `(earliest − latest) ÷ 7`,
clamped, with `daily_hw_l` as the floor. The per-pair walker was only
ever meant for the heating-only component.

The bug surfaced on the first live run: ~5 L/day real draw + ±5 L
sensor jitter across thousands of broadcasts inflated to 215 L/day,
collapsing `estimated_days_remaining` to 2.5 days on a near-full tank.
Regression test seeds 7 days of jittery 30-min broadcasts and asserts
`avg_daily ∈ [1, 15]` L/day.

### 18.3 ONS-anchored historical PPL correction — `cbf665c` + `60e02dc` + `b0c0b17`

A unique-to-this-instance correction for the 2025 broken-scrape
window. v1's HomeFuelsDirect scrape was stuck for ~7 months (51.99p
plateau over 219 days) and v1's monthly cron had also been writing
spurious refill_period rows (start `2025-04-25 10:03:43` + monthly
first-of-month endpoints, all sharing `refill_ppl=50.99`). Both came
across in the migration.

**New code (inert until invoked):**
- `monthly_avg_ppl` table — ONS RPI Heating Oil monthly averages
  (series MM23/KJ5U).
- `kerotrack import-ons-prices --csv series-XXXXX.csv` — parses the
  ONS CSV (skips header + annual + quarterly rows, divides
  pence-per-1000L by 1000).
- `kerotrack rebuild-costs [--src-db PATH] [--apply] [--brief]` —
  re-detects refill_periods using a `PplResolver` that prefers
  (1) live-changing sensor PPL, (2) ONS month when sensor stuck for
  ≥14 days, (3) linear interpolation between real anchors (ONS month,
  `actual_refill_costs`, first reliable post-fix sensor reading).
  Read-only by default; `--apply` to write. `--src-db` runs against an
  alternative DB so a snapshot can be validated before touching the
  live volume.
- Spurious migrated rows are filtered by their unique signature
  (start `2025-04-25 10:03:43` + end `*-01 06:18:02`).

**Math fix landed alongside (`60e02dc`):** `cost.py:_per_pair_cost`
also moves to `net_consumption × time-weighted-average-PPL`. Without
this the Sunday cost-analysis cron would silently undo every rebuild
because `_detect_periods` re-runs on every job invocation. Caught on
the first apply against live data: rebuild produced £304.62 → next
cost-analysis run rewrote it to £2 708.07 (the per-pair-sum bug).

**Process — backups + offline validation:**
- Live snapshot to `legacy/kerotrack-pre-ons-20260426-105509.db`
  before any code change.
- ONS CSV imported into a working copy of the snapshot.
- `historical_deliveries.txt` imported via the existing
  `import-historical` CLI (8 invoiced refills loaded).
- Dry-run rebuild against the working copy printed a before/after
  diff; user reviewed before any write to live.
- In-container second snapshot at
  `/app/data/kerotrack.db.preons-20260426-112255` before the apply.

**Live result:** 9 → 2 refill_periods (7 spurious removed), ✓ invoiced
badge on the 2023-06 → 2024-10 row that matched `10/10/2024`,
avg_daily £1.28, avg_monthly £39.08, avg_annual £469.01,
percentage_with_actual_data 50%.

### 18.4 Chart visual fixes — `b0c0b17`

Caught while reviewing the live dashboard:

- **Trends · Daily consumption** was summing `litres_used_since_last`
  across ~48 broadcasts/day, inflating ~5 L/day real draw to 50 L
  bars. Switched to `first-minus-last` of `litres_remaining` per
  calendar day (same approach as the cost rebuild). Year heatmap
  uses the same derivation.
- **Costs · PPL history** was fetching `limit:365 order:asc`, which
  returns the OLDEST 365 readings (back to 2023). Switched to a
  `since` filter for the trailing 12 months.
- **Forecast · Fan chart** history was 3 years of dense ingest; now
  clipped to last 12 months and downsampled to first-reading-per-day.
- **Forecast · HW split** shows an inline note when today's HDD = 0
  ("Today's HDD is zero — boiler estimated to be on hot water only")
  so the 100%-HW donut isn't misread as a bug.

### 18.5 Test count

Backend: **275 tests passing** (was 238 at end of §16; +11 from §17
A-block, +11 from the rebuild module, +others from intermediate fixes
and regressions).
Frontend: **7 tests passing** (unchanged; Playwright config + smoke
spec landed in §17 C2 but aren't part of the unit count).

---

## 19. Outstanding work

Everything in the original spec, the §17 backlog and the §18 live
shakedown is done. No code-side work remains. Two observation items
worth a glance over the next couple of weeks:

- **Sunday 2026-05-03 notifier** — the first scheduled v2 notifier
  run in production. Worth eyeballing the Gotify message to confirm
  the rich Markdown + refill-aware deltas land correctly off real data.
- **Next real refill** — once a delivery happens, the sensor will
  flag a new refill marker. `_detect_periods` will pair it with the
  migrated 2025-04-25 marker and produce a third refill_periods row
  spanning the 2025-04 → 2026-NN window. This will be the first row
  that uses the post-fix BoilerJuice scrape data (~106p) for its
  cost calculation; values should come out reasonable without needing
  the rebuild routine.

The `legacy/kerotrack-pre-ons-20260426-105509.db` snapshot is held in
a gitignored directory. Safe to keep until the next refill cycle
confirms cost analysis still produces sane numbers, then delete.
