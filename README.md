![logo](assets/logo.png)

# KeroTrack

KeroTrack is a domestic heating-oil monitoring system that ingests MQTT messages from a Watchman Sonic transmitter (via LilyGO LoRa32 + OpenMQTTGateway) and exposes them through an API + SPA dashboard.

> **Status: pre-alpha.** This repo currently contains only the design spec; backend and frontend implementation start once the plan is approved.

## Architecture

- **`backend/`** — FastAPI + async SQLAlchemy + APScheduler + `aiomqtt`. Owns ingest, analysis, scheduling, notifications, and the JSON API. Single image, single process.
- **`frontend/`** — SvelteKit + TypeScript + Tailwind + ECharts SPA, served by nginx.
- **`compose.yaml`** — two-service stack (`backend`, `frontend`) on a private Docker network, persistent named volumes for DB and logs.
- **DB-backed settings** — tank dimensions, boiler spec, MQTT credentials, schedules, Apprise URLs, etc. live in a `settings` table, edited via `/api/settings` and the Settings page in the UI. The only `.env` keys are bootstrap concerns: `DATABASE_URL`, `PORT`, `TZ`, `LOG_LEVEL`.
- **In-process scheduling.** APScheduler runs the analysis, cost analysis, and notifier jobs — no host cron, no systemd units, no separate system user.

## Integrations

- **[KeroTrack-display](https://github.com/MrSiJo/KeroTrack-display)** — CYD ESP32 dashboard. Reads `oiltank/level` and `oiltank/analysis` over MQTT.
- **Home Assistant** — `ha-oilanalysis.yaml` and `lovelace-dashboard.yaml` provide sensors and a Lovelace dashboard.

## Plan

The full design + implementation plan is in [`docs/plans/2026-04-25-v2-redesign.md`](docs/plans/2026-04-25-v2-redesign.md).

## Layout

```
KeroTrack/
├── backend/        # FastAPI app (kerotrack package), pyproject.toml, Dockerfile, tests
├── frontend/       # SvelteKit + TS app, nginx Dockerfile
├── compose.yaml    # docker compose stack
├── docs/           # plans + ADRs
└── assets/         # logo, screenshots
```

## License

Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0). See [LICENSE](LICENSE).
