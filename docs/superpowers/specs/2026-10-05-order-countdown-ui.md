# Order countdown UI: one answer to "when do I order?"

**Status:** Approved by the owner 2026-10-05 (design critique of the live app).
**Date:** 2026-10-05

## Problem

The app answered "when do I need to order?" in five places with four different answers: dashboard badge (order by 2027-02-15, correct), dashboard tank card ("Days to empty 155", actually the reserve date), dashboard Forecast tile ("order in 141d window"), Forecast page (legacy Winter/Mild/Summer cards: 169/225/225 days, empty 2027-03-23 and 2027-05-18 from the old flat-rate model), and the Buying page. The data is good; the contradictions and the volume make it heavy.

## Rules

- **Single source of truth:** the runway (`GET /api/buying/summary`, active scenario, falling back to `normal`) for order-by and reserve dates. No other projection is shown as a date.
- **Dates** display as `15 Feb 2027` with a relative count (`in 133 days`); never `YYYY-MM-DD HH:MM:SS` in the UI.
- **Scenario names** are the runway ones everywhere: Normal, Mild then cold, Cold.
- **State colours:** buy_now green, deadline amber, overdue red, wait blue, no_room and unknown neutral.
- Plain UK English, no em or en dashes in UI copy. No personal details.

## Changes

1. **OrderCountdown card** (new shared component), used at the top of the dashboard (replacing the thin `BuyingBadge` strip) and at the top of the Buying page:
   - Headline: `ORDER BY 15 FEB 2027 · 133 days` and the state pill.
   - One plain sentence explaining the state, e.g. wait: "Price 110.0p (Home Fuels Direct, £577.71) is above your 95.0p trigger." buy_now: "Price 94.0p is at or below your 95.0p trigger. A good time to order." deadline: "Order within N days." overdue: "Past the order by date. Order now." no_room: "Not enough room in the tank for a 500 L delivery." unknown: "No fresh prices yet." When no trigger is set: "No price trigger set (Settings > buying)."
   - Timeline bar: today, order by marker, reserve (run out) marker, scaled by days; the stretch from today to order by is the buy window.
   - Scenario range in one line: "Depending on the winter: order between 13 Feb and 15 Feb" (min and max order_by across scenarios; omit when all equal or only one).
   - Whole card links to `/buying` on the dashboard.
2. **Dashboard:** the tank card's "Days to empty" becomes "Days to reserve" with the date formatted (it already comes from the runway via analysis keys). The Forecast tile shows the order by date and days from the buying summary instead of "order in Nd window".
3. **Forecast page becomes the usage and runway page:**
   - Remove the legacy Winter/Mild/Summer scenario cards and any figure not derived from the runway.
   - Headline stats: Order by, Reserve reached (run out), Hot water L/day, Heating factor k.
   - Keep the history/fan chart for past usage; show the runway chart (moved from Buying) with the scenario range line under it.
4. **Buying page becomes the prices and decision page:**
   - OrderCountdown at the top.
   - Quotes: one row per supplier (its default, non-urgent option); a "Show all delivery options" toggle reveals urgent windows.
   - Price history: until there are quotes on at least 14 distinct days, show a compact text summary (today's best effective price, national index, change since the first quote) instead of the chart; then the chart, with the national index drawn even when it has few points (show symbols).
   - Runway chart moves to Forecast (link "See the runway").
   - Calibration panel moves to Settings > boiler, rendered next to the burner minutes setting.
5. **Settings > boiler:** the calibration panel (current k, hot water L/day, Calibrate button, proposal text) appears in the boiler group.

## Out of scope

Backend changes beyond what the UI needs (none expected: everything is in `/api/buying/summary`, `/api/buying/quotes`, `/api/buying/calibrate`). Changing the owner's settings.

## Verification

vitest for the new pure helpers (date formatting, scenario range, state sentence, timeline geometry, "enough history" rule, quote grouping); `npm run check`, `npm test`, `npm run build`; browser check on a local instance with SYNTHETIC data (dashboard, Buying, Forecast, Settings > boiler), zero console errors.
