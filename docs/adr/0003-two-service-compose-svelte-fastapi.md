# ADR-0003: Two-service compose stack — FastAPI backend, SvelteKit frontend

**Status:** Accepted
**Date:** 2026-04-25
**Plan:** [`docs/plans/2026-04-25-v2-redesign.md`](../plans/2026-04-25-v2-redesign.md) §2, §8

## Context

v1 was a single Flask app serving Jinja2 templates and Plotly figures with Socket.IO + eventlet for live updates. It mixed templating, server-rendered charting, MQTT subscription, and HTTP serving in one process. The architecture made the "modernise the UI" path painful — there was no API surface to design against, and Plotly server-rendering made chart customisation expensive.

Two packaging approaches were considered: a single image (FastAPI serves the built SPA out of `/app/static`) or two images (FastAPI backend, nginx-served frontend).

## Decision

KeroTrack v2 ships **two services** under `docker compose`:

- `backend` — FastAPI on `:8742`, owns ingest, analysis, scheduling, notifications, and the JSON API. No templating.
- `frontend` — SvelteKit + TypeScript SPA built with `@sveltejs/adapter-static`, served by `nginx:alpine` on `:8743`.

The backend exposes JSON only. The frontend talks to it over HTTP and SSE.

## Consequences

- Frontend and backend can be rebuilt and restarted independently.
- nginx handles compression, SPA fallback, and caching the frontend serves are good at — Python doesn't need to.
- Two images instead of one — slightly more compose surface area, but the separation pays for itself in independent rebuild cycles.
- The frontend is a static bundle; deploying a new build is fast and cache-friendly.
- The API surface gets exercised by the frontend in development, which keeps it healthy. No "the dashboard is just templates so the API can drift" trap.
