# Past usage trend driven by the Nest heating model

**Status:** Approved by the owner 2026-10-05.
**Date:** 2026-10-05

## Why

The first dotted trend on the Forecast page (7848a74) is a robust smoother over the sensor alone. Through the summer 2026 glitch (phantom echo near 575 L, drop outs, then a sensor stuck near 400 L) it falls fast through June and July and then runs flat. The Nest model says the summer had zero heating hours, so the tank fell at hot water rate (about 0.87 L/day) the whole time: a straight slope from 510 L on 2026-05-20 to about 392 L on 2026-10-05, where the sensor reads 403 L (one 10.5 L step away). Over the heating season the model is about 12% light against the sensor, so the sensor must still set the level there.

## Out of scope

The dashboard tank level, the runway projection, calibration. The trend is display only.

## Backend

`GET /api/buying/heating-hours?days=N` (authenticated, `1 <= N <= 730`, default 400) returns one item per day from today minus N days to today:

`{"items": [{"date": "YYYY-MM-DD", "hours": 1.2, "source": "daily" | "monthly" | "average"}]}`

- `daily`: a `nest_heating_daily` row.
- `monthly`: that month's `nest_heating_monthly` total spread evenly over its days.
- `average`: neither exists; the calendar month's mean across all years (`expected_hours_fn`), as the projection does.

A pure function `daily_heating_hours(start, end, daily, monthly)` does the work; the route only loads rows.

## Frontend trend

Inputs: daily medians of the readings, daily heating hours, `hw_l_per_day` and `l_per_heating_hour` from the buying summary. With no `l_per_heating_hour` (HDD model) or no heating hours, the existing sensor only trend is used unchanged.

1. Expected use for day d: `u(d) = hw + a * hours(d)`; cumulative `E(d)`.
2. Offset `r(d) = median(d) + E(d)`: constant where sensor and model agree.
3. A day is trusted when at least 80% of its readings sit within 15 L of its median, and it is not impossible: its offset is within 30 L of a running offset level (an exponential average over accepted days, seeded from the first 14 candidates). The level runs forwards and backwards; passing either is enough, so both sides of a glitch can be trusted at different levels.
4. Stuck sensor: a run of days whose medians stay inside a 32 L band (three sensor steps, so flicker stays in; untrusted days outside the band are see through) is stuck when the model expects more than 45 L of use between its first and last trusted day. Then every day from where the sensor first landed on its final level (within 11 L) is untrusted.
5. Offset curve: a robust local fit of `r` over each unbroken run of trusted days (runs split at gaps over 7 days, so the far side of a glitch is never blended in). Between runs the offset is interpolated linearly in time, so any gap is spread evenly and the two sides join without a step; before the first or after the last trusted day it holds (pure model).
6. Trend `= offset(d) - E(d)`, clamped never to rise between refills (a rise of 300 L or more splits segments, as now).

## Tests

Backend: the pure function (daily beats monthly beats average, spreading, empty data), the route (401 unauthenticated, bounds, shape). Frontend: the existing trend tests still pass through the fallback; model tests for a stuck sensor following the model slope, a phantom month riding the model, winter drift following the sensor, and joining two offset levels without a step.
