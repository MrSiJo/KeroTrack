# KeroTrack-v2 — Code Quality Review

**Date:** 2026-07-08 · Part of a review of all `*Track` apps; cross-app index at `C:\code\TRACK-APPS-CODE-REVIEW.md`.

## How to use this document (instructions for a Claude session)

This is a code-quality review of KeroTrack-v2, one of Simon's personal projects. If you've been given finding IDs (e.g. "implement KERO-H1 and KERO-H3"):

1. **IDs** are `KERO-<PRIORITY><n>` — `H` high, `M` medium, `L` low/polish.
2. **Scope discipline:** findings are about code quality, correctness, optimisation, and consistency — do NOT add features, change end-user functionality, or redesign UI. Keep each fix minimal and targeted.
3. **This is a personal project** — don't add enterprise ceremony unless a finding explicitly calls for it.
4. **Deployment caution:** this app runs in production on a remote docker host (`ssh://root@172.16.0.83`, docker context `docker-host`) with prod data bind-mounted via a local-only `compose.override.yaml`. Do not deploy or touch prod data unless explicitly asked.
5. **Verify line numbers before editing** — this is a snapshot from 2026-07-08; re-locate code by the symbols/strings named in the finding.
6. Run the test suites (pytest — ~256 backend tests; vitest + Playwright frontend) before and after changes; each finding's `Verify:` note gives a functional check.
7. **Secrets:** untracked local `.env` files are known and fine — do not "fix" them.
8. **Commits:** one per finding (or tightly-related group), message referencing the ID, e.g. `fix: share trusted-readings clause across analysis and notifier (KERO-H3)`.

**Effort key:** `quick` = minutes, single-file · `small` = under an hour · `involved` = multi-file / needs care and testing.

---

**Stack:** Python 3.12 / FastAPI + async SQLAlchemy 2 (SQLite/aiosqlite, WAL) + APScheduler + aiomqtt backend; SvelteKit 2 (Svelte 5 runes) + Tailwind 3 + ECharts SPA frontend; two Docker containers (nginx-served static UI proxying `/api` → uvicorn) published to GHCR via GitHub Actions + release-please.

**Overall assessment:** An unusually healthy hobby codebase. The architecture is coherent (single app factory, DB-backed settings with audit + change subscribers, duck-typed MQTT publisher for testability), the sensor noise-suppression logic is carefully reasoned and commented with real-world incident references, there are ~256 backend tests plus frontend unit/e2e tests, pre-commit security hooks, ADRs, and a genuinely good security posture (Argon2id, CSRF, SSRF guards, non-root containers, pinned security invariants test). The findings below are mostly seams: one orphaned data pipeline, a documented behaviour that doesn't hold at runtime, a handful of blocking calls in async paths, and duplication that has already produced one inconsistency.

## High priority

### KERO-H1 — The HDD data pipeline is orphaned — nothing in v2 ever writes `hdd_data`
*(effort: involved)*
`HddDatum` is read by the consumption analysis (`backend/kerotrack/analysis/consumption.py:245-263`), cost analysis (`backend/kerotrack/analysis/cost.py:112-127`) and served via `/api/hdd`, but the only writer in the entire codebase is the one-shot v1 migration (`backend/kerotrack/migration/v1_to_v2.py:34`). The table is frozen at 12 migrated monthly rows. Compounding it, `consumption.py` does per-day lookups against those monthly keys: `today_hdd = recent_hdd_data.get(today_str, 0.0)` (`consumption.py:510`) only ever matches on the 1st of a month, so `today_hdd` is ~always 0 → `heating_l` is forced to 0 (`consumption.py:558-559`), the HDD scaling clamp never runs, the days-remaining cap always uses the 700-day no-HDD branch, and `consumption_per_hdd`/`cost_per_hdd` only reflect the migrated window and will decay to 0 as periods roll forward. Each reading already computes `heating_degree_days` (`ingest/recalc.py:384`).
**Fix:** either aggregate the per-reading HDD values into daily `hdd_data` rows (a small scheduled job), or delete the table and the HDD-derived metrics honestly. Right now a large fraction of the analysis code is computing on a dead input. (See also KERO-L8 — `upcoming_month_hdd` folds into this.)
**Verify:** after fix, `SELECT COUNT(*) FROM hdd_data` grows over time and `heating_l` is non-zero on cold days (or the metrics are gone).

### KERO-H2 — Per-IP rate limiting doesn't work as documented
*(effort: small)*
CLAUDE.md and `backend/kerotrack/api/rate_limit.py:6-9` claim slowapi keys on the real client IP via `X-Forwarded-For`, "the default with uvicorn[standard]". uvicorn's `proxy_headers` is on by default, but `forwarded_allow_ips` defaults to `127.0.0.1`; inside the compose network the peer is the frontend nginx container's bridge IP, so the XFF header set at `frontend/nginx-frontend.conf:45` is *ignored* and every client shares one rate-limit bucket keyed on the nginx container IP. For a single-operator app a global 5/min bucket is arguably fine — but the docs and the careful XFF-sanitising nginx config describe a mechanism that isn't active.
**Fix:** set `FORWARDED_ALLOW_IPS` (env) to the frontend service/network in `compose.yaml`, or key the limiter globally on purpose and update CLAUDE.md. Note the backend port is also published on the host (`compose.yaml` `9176:9176`), so direct API traffic bypasses the XFF-sanitising proxy — if you widen `forwarded_allow_ips`, keep it scoped so direct callers can't spoof XFF to rotate buckets.
**Verify:** two clients hitting login rate-limits independently (or docs updated to say "global bucket").

### KERO-H3 — `noise_suppressed` filter duplicated 6× — and it has already drifted
*(effort: small)*
The `raw_flags LIKE '%noise_suppressed%'` trusted-row clause is copy-pasted in `analysis/consumption.py` (4 sites), `analysis/cost.py:101-102`, `ingest/mqtt.py:54-56`, `notifier/apprise_notifier.py:71-73` and `api/routes/status.py:29-31`. The predicted failure mode has already happened: `notifier/apprise_notifier.py:89-95` (`_latest_reading`) has **no** noise filter, so the weekly digest's "⛽ Tank Level" line can report a multipath spike as the current level, while the dashboard (`status.py`) correctly skips it.
**Fix:** extract one shared `trusted_readings_clause()` (e.g. in `models/reading.py`) and use it everywhere; then make the notifier's latest-reading trusted-only (it should be).
**Verify:** insert a noise-suppressed spike row in a test DB; weekly digest and dashboard must agree on the level.

## Medium priority

### KERO-M1 — Blocking calls inside the event loop
*(effort: small)*
(a) `apprise.notify()` at `notifier/apprise_notifier.py:484` is synchronous network I/O; a slow Gotify/SMTP target stalls the whole loop (SSE, ingest) for the duration. Wrap in `asyncio.to_thread(...)` or use Apprise's async API. (b) `socket.getaddrinfo` at `settings/url_guard.py:76` runs inside async `SettingsService.set`; a hanging DNS lookup freezes the loop on a settings save. Use `loop.getaddrinfo()` or `to_thread`. (c) Minor: Argon2 hashing in the auth routes and `PriceCache` file I/O are also sync-in-async, but both are small/rare enough to leave.

### KERO-M2 — Health endpoint always returns 200, so container healthchecks can't fail on a broken DB
*(effort: quick)*
`api/routes/health.py` sets `status: "degraded"` in the body but never a non-200 code; the Docker healthcheck (`curl -fsS`) at `backend/Dockerfile:24` and `compose.yaml` therefore reports healthy with the DB down.
**Fix:** return 503 when `status != "ok"` (or at least when `db == "down"`), which is exactly what the compose `depends_on: service_healthy` gate is there for.

### KERO-M3 — `PriceService.current_ppl()` does a full scrape-with-retries inline in the ingest path; cache path hardcoded
*(effort: small)*
Every MQTT reading calls `current_ppl()` → `refresh()` (`prices/service.py:71-73`); when the cache TTL has lapsed and both providers are down, that's 2 sources × 3 attempts × 1s delays (~6s) of stall per reading inside `handle_payload` (`ingest/mqtt.py:188`), every 30 minutes, forever (total failure doesn't write a cache entry, so it re-runs each time).
**Fix:** add a negative-result cooldown, or move price refresh onto the scheduler and have ingest read the cached value only. Separately, `main.py:64` hardcodes `Path("/app/data/price_cache.json")` while the DB path is configurable via `DATABASE_URL` — on the documented non-Docker dev path this tries to create `/app/data` and fails on every reading with a logged exception. Derive it from a data-dir setting alongside the DB.

### KERO-M4 — Backend dependencies unpinned; Docker layer caching defeated
*(effort: small)*
`backend/pyproject.toml` uses only `>=` ranges with no lock/constraints file, while `compose.yaml` uses `pull_policy: always` + `:latest`; a rebuild can silently pick up new FastAPI/SQLAlchemy/apprise majors. Also `backend/Dockerfile:14-17` copies `kerotrack/` *before* `pip install .`, so every source edit reinstalls all dependencies.
**Fix:** add a `constraints.txt` (pip-compile output) used in the Dockerfile; install deps in an earlier layer, then copy the package.
**Verify:** two consecutive builds with a source-only change reuse the dependency layer.

### KERO-M5 — Uncommitted security work sitting in the working tree
*(effort: quick — but review the diff first)*
`url_guard.py` (the whole SSRF guard, referenced by tracked `settings/service.py`) is untracked, plus modified `auth.py`, `settings/service.py`, `nginx-frontend.conf` and 113 new lines of security-invariant tests. Given the deploy ritual is commit → push → pull image on the docker host, **HEAD currently doesn't build/run** (service.py at HEAD can't import url_guard — or the working tree diverges from what's deployed).
**Fix:** commit it. Also: `AGENTS.md` is a byte-identical untracked duplicate of `CLAUDE.md` (it will drift — track it, or make it a one-line pointer), and `snapshots/` is untracked but *not* gitignored so it pollutes `git status` (add to `.gitignore` next to `legacy/`).
**Verify:** fresh clone of HEAD imports/builds and tests pass.

## Low priority / polish

### KERO-L1 — Dead code
*(effort: quick)* — `_CRON_RE` in `settings/service.py:226` compiled and never used (cron validation uses `cron_converter`). `RecalcContext.tank_length_cm`, `tank_width_cm`, `thermal_coefficient` (`ingest/recalc.py:53-57`) loaded from settings every reading and never used (the volume model is linear in height only). `EnergyMetric` model + `energy_metrics` table exist only for the migration to copy into — nothing reads them. `boot = get_bootstrap()` at `cli.py:349` and `:419` assigned and unused; `cli.py:431` `return 0` unreachable.

### KERO-L2 — pytest config duplicated and stale
*(effort: quick)* — root `pytest.ini` and `backend/pyproject.toml [tool.pytest.ini_options]` both configure testpaths/asyncio-mode; the root one suppresses *all* `DeprecationWarning`s (hides upgrade signals), and the pyproject one filters a `passlib` warning although passlib isn't a dependency (auth is argon2-cffi). Keep one config, narrow the filter.

### KERO-L3 — `SettingsService.get` cache race
*(effort: quick)* — `get()` (`settings/service.py:67-80`) populates `self._cache` outside the lock that `set()` holds; a `get` reading the DB just before a concurrent `set` commits can write the stale value into the cache *after* `set` cached the new one, and it sticks until the next set/invalidate. Near-theoretical single-operator, but a `key in cache` re-check under the lock is a 3-line fix.

### KERO-L4 — ECharts lifecycle boilerplate duplicated across 5+ components
*(effort: small)* — `LineChart`, `BarChart`, `ScatterChart`, `CalendarHeatmap`, `ForecastFan` each reimplement init/resize-listener/dispose/`$effect` re-render (e.g. `LineChart.svelte:96-119`). A shared `useEchart(el, buildOption)` helper (or Svelte action) collapses ~40 lines per component and keeps resize/dispose uniform. Also: charts always init with `KEROTRACK_DARK_THEME` despite a theme toggle existing.

### KERO-L5 — Unbounded append-only tables with manual-only pruning
*(effort: small)* — `raw_captures` grows one row per reading (~17k/yr; `kerotrack prune-raw` exists but is break-glass) and `cost_analysis` inserts a new row per scheduled run because `_persist` keys on second-resolution `analysis_date` (`analysis/cost.py:530-544`). Volumes are trivial for SQLite, but a small retention sweep in the scheduler would keep the DB from growing forever.

### KERO-L6 — `refill_date` accepted as a free-form string
*(effort: quick)* — `api/routes/refills.py:17` and the CLI take any string; a malformed date silently breaks `_match_actual_cost` and the manual-refill anchor (they `parse_local` → `None` and skip). A Pydantic validator enforcing `YYYY-MM-DD HH:MM:SS` would fail loudly at entry instead.

### KERO-L7 — Magic numbers in detection
*(effort: quick)* — `detect_refill`'s `air_gap_decrease > 5` cm (`ingest/recalc.py:128`) is hardcoded while every comparable threshold lives in settings; fine as-is, but worth a named constant with a comment like its siblings.

### KERO-L8 — `upcoming_month_hdd` never means "upcoming month"
*(effort: quick)* — `consumption.py:518-524` looks up next month's first-of-month key in a window that ends *today*, so it always falls through to "most recent HDD row". Folds into KERO-H1; if HDD is revived, this field needs a real source (or renaming).

## Patterns snapshot

- **Config:** two-tier — pydantic-settings `.env` for boot secrets (`APP_SECRET_KEY`, ports, TZ, DB URL) + DB-backed `settings` table (typed catalogue, audit log, live change subscribers) for everything else
- **Logging:** stdlib `logging` module-level loggers throughout; no structured logging; log level from env
- **DB access:** async SQLAlchemy 2.0 ORM, `async_sessionmaker`, short-lived session-per-operation; SQLite with WAL/pragmas via connect listener; schema via `create_all` (no Alembic)
- **Frontend:** SvelteKit 2 + Svelte 5 runes, adapter-static SPA, Tailwind 3, ECharts; typed hand-rolled fetch client with CSRF header + 401 callback
- **Tests:** pytest + pytest-asyncio (256 tests incl. a pinned security-invariants suite), respx/freezegun; frontend vitest unit tests + Playwright e2e; no coverage tooling
- **Docker:** two containers (nginx UI → FastAPI API), healthchecks in both Dockerfiles *and* compose, non-root backend + tini, restart policies, named volumes with gitignored bind-mount override; GHCR images via GH Actions + release-please semver
- **Lint/format:** pre-commit = gitleaks + bandit + ruff (S-ruleset only) + custom RFC1918-IP-literal blocker; svelte-check/tsc on frontend; no Python formatter enforced
- **Scripts:** Python CLI (`kerotrack` entry point, argparse, dry-run-by-default break-glass commands) + one Node `.mjs` screenshot script; no PowerShell/bash scripts
- **Git hygiene:** clean — no secrets, data dumps, caches or `node_modules` tracked; only gaps are the uncommitted working-tree items in KERO-M5
