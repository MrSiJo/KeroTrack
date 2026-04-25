# ADR-0002: Runtime settings live in the database, not `.env`

**Status:** Accepted
**Date:** 2026-04-25
**Plan:** [`docs/plans/2026-04-25-v2-redesign.md`](../plans/2026-04-25-v2-redesign.md) §5

## Context

v1 read all configuration from `config/config.yaml` — tank dimensions, boiler spec, MQTT credentials, Apprise URLs, schedules, detection thresholds, oil-price scraper URLs. Editing required SSH-ing to the host and restarting services.

The sibling FinTrack project keeps app secrets in `.env` and operational toggles in a `settings` table edited via the UI. JobTrack uses `pydantic-settings` with `.env` for everything.

## Decision

KeroTrack v2 stores **all runtime configuration in a `settings` table** in SQLite, edited via `/api/settings` and a Settings page in the SvelteKit UI.

`.env` carries only the values that must be readable **before the database is open**:

- `DATABASE_URL`
- `BACKEND_PORT` / `FRONTEND_PORT`
- `TZ`
- `LOG_LEVEL`
- `VITE_API_URL` (frontend build-time)

Defaults for every setting live in code (`kerotrack/settings/schema.py` + `seeds.py`). Seeding is idempotent — it only inserts keys that are missing, never overwriting operator changes.

Secrets (MQTT password, etc.) are flagged in the schema, redacted on read, and audit-logged on write without storing the value.

## Consequences

- Operators edit configuration from the dashboard — no SSH, no YAML, no service restart.
- The settings service can broadcast changes to live subscribers (scheduler reschedules jobs when cron expressions change; MQTT subscriber reconnects when broker settings change).
- Settings travel with the database backup.
- Cost: more code than just reading a YAML file. Mitigated by the schema being a single source of truth.
- Cost: an audit log table. Worth it for "who/what changed the cron at 3am?" debugging without a real auth model in place.
