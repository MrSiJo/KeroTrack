# ADR-0001: Record architecture decisions

**Status:** Accepted
**Date:** 2026-04-25

## Context

v1 grew without recorded design decisions, so the rationale behind choices (Flask + Socket.IO, YAML config, host cron, separate MQTT service) had to be reconstructed from the code each time a refactor was considered.

## Decision

Architecture decisions for v2 are recorded as ADRs in `docs/adr/`. Each ADR is a short Markdown file numbered sequentially, capturing **context, decision, consequences**. ADRs are immutable once accepted; superseding decisions are written as new ADRs that reference the older one as `Superseded by ADR-NNNN`.

ADRs are not implementation plans. Plans live in `docs/plans/` and reference the ADRs they depend on. Plans can change; ADRs cannot.

## Consequences

- Any non-trivial decision (framework choice, persistence choice, transport choice, configuration model) gets an ADR before code lands.
- Reviewing the v2 codebase in a year does not require reading commit messages to understand "why is it Svelte and not React?".
- Cost: a small amount of upfront writing per decision.
