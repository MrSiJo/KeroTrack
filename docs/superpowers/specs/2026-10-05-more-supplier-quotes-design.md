# More supplier quotes: The Heating Oil Company, NWF, Western Fuel (and BoilerJuice)

**Status:** Implemented 2026-10-05. Owner approved the direction 2026-10-05 ("unpark the email suppliers").

> **Spike outcome (2026-10-05): all four suppliers work over plain HTTP; none dropped.**
> - The Heating Oil Company: the GET quote URL works headless once `email` and `heardfrom` are sent; server rendered HTML.
> - NWF: prices from `POST /wp-json/nwf-fuels/v1/quote-update` (JSON body `{"action":"get_costs","data":{...}}`); delivery tiers, dates and any per tier charge (ex VAT) from `POST /wp-admin/admin-ajax.php` `action=get_delivery_options`. The marketing opt in is a separate call (`send_opt_in_email_to_active_campaign`) that is never made.
> - Western Fuel: `POST /api/quote` with JSON `{litres, fuelType: "Kero", tankerType: "Standard", postcode, email}` returns tiers with `totalPence`, `serviceChargePence` (£12, which explains the stated ppl not reconciling) and `deliveryDate`.
> - BoilerJuice: GET the quote form for a session cookie and `authenticity_token`, POST the form (302), GET the quote page; cards carry `data-delivery-date` and `data-price`. `deliveryN` means within N working days; N <= 2 is treated as urgent. `opt_out_email=1` is sent.
> - Manual "Check prices now" (`POST /api/buying/run`) runs job `buying_all`, which polls every configured provider; the scheduled `buying` run polls only frequent providers, and `buying_daily_quotes` only the daily ones (without refreshing the national index).
**Date:** 2026-10-05

This spec is self contained: a fresh session should be able to start from it without the conversation that produced it. Read the "Where things stand" section first, then the supplier dossier.

> **Private values are NOT in this public repo.** The owner's postcode and email catch-all domain live in the owner's private Claude memory (`user_oil_ordering.md`, "Supplier probe" and "Quote emails" notes) and, at runtime, only in the production `settings` table (`buying.postcode` is a secret setting). Tests use postcode `ZZ99 9ZZ` and domain `example.net`. Never write the real values into code, tests, fixtures, docs, commit messages or PR text.

## Where things stand (as of 2026-10-05, main `ba411b7`)

KeroTrack-v2 already has a working buy planner (spec `2026-10-04-buy-planner-design.md`, plan `../plans/2026-10-04-buy-planner.md`):

- **Quotes package** `backend/kerotrack/quotes/`:
  - `models.py`: `QuoteRequest(postcode, litres, tanker)`, `QuoteOption(supplier, litres, delivery_by, delivery_label, urgent, ppl_net, total_inc_vat, fees_inc_vat)`, `effective_ppl(total_inc_vat, litres) = total / 1.05 / litres * 100` (pence per litre ex VAT, fees included), `best_option(...)` (cheapest non urgent), `USER_AGENT = "KeroTrack/2 (+https://github.com/MrSiJo/KeroTrack)"`, `PollResult(supplier, options, error)`.
  - `homefuelsdirect.py`: the only live provider. Endpoint and parsing are constants in the module (no user supplied URLs, so no SSRF surface).
  - `registry.py`: `PROVIDERS = {"homefuelsdirect": HomeFuelsDirect()}`; `poll(client, req, names)` does one try plus one retry per provider and never raises; error text is scrubbed of URL query strings (`?<redacted>`) so the postcode never reaches the DB, logs or API.
  - `store.py`: `save_poll`, `save_index`, `latest_poll`, `best_recent(sf, now, max_age_h=36, until=None)`, `history`.
- **Table `price_quotes`**: one row per option per poll (`ok=0` row with `error` on a failed provider). Index rows: `kind="index"`, supplier `boilerjuice`.
- **Buying job** `backend/kerotrack/buying/service.py` `run_buying(...)`, cron `schedule.buying_cron` default `0 7,13 * * *`: refreshes HDD, polls `buying.providers` (default `["homefuelsdirect"]`) when `buying.postcode` is set, records the BoilerJuice national index, runs the runway projection, computes the buy signal, publishes retained MQTT `oiltank/buying`, alerts via Apprise/Gotify on entering `buy_now` / `deadline` / `overdue`.
- **Signal "best quote"** currently = cheapest non urgent ok quote **in the latest poll** (36 h freshness), via `_best_latest` in `buying/service.py`. `current_ppl` for readings uses `best_recent` (36 h window).
- **UI**: `/buying` shows one row per supplier (`groupQuotesBySupplier` in `frontend/src/lib/countdown.ts`), with a "Show all delivery options" toggle; supplier display names come from a map in `frontend/src/lib/buying.ts` (`homefuelsdirect` -> "Home Fuels Direct"; unknown keys shown as is).
- **Settings group `buying`**: `buying.postcode` (secret), `buying.order_litres` 500, `buying.min_order_litres` 500, `buying.tanker` "standard", `buying.providers` json, `buying.trigger_ppl`, `buying.safe_fill_pct`, `buying.warn_days`, `buying.lead_time_days`, `buying.winter_lead_extra_days`.
- **yournrg** is retired (does not deliver to the owner's area). Its old `prices.yournrg_url` key is in `RETIRED_KEYS`.

## Goal

Get real, all in, 500 L quotes for the owner's postcode from the suppliers the owner actually buys from, so the buy signal and Buying page compare like for like. Suppliers that require an email address are polled **once a day**; email free ones keep their current cadence.

## Owner decisions

1. Suppliers that require an email: **once a day**, default **10:30** local (UK suppliers reprice each morning; mid morning catches today's price). Make the time a setting so it can move once price history shows when each supplier actually reprices.
2. Email addresses: one dedicated address per supplier from a pattern setting, `{site}` = provider name, at the owner's catch all domain (private value, set in production settings only). Spam is acceptable; per supplier addresses make it filterable.
3. Never send any marketing consent field; leave consent unticked or omit it.
4. A supplier that can only be read by driving a real browser is **dropped**, not built.
5. Comparison is always on the all in total for 500 L (effective ppl), never on the supplier's stated ppl (fees change the ranking: BoilerJuice has the 2nd lowest ppl but a £12.98 service charge).

## Supplier dossier (evidence from 2026-10-04, owner's postcode, 500 L, standard tanker)

All totals are inc 5% VAT and fees.

| Supplier | Total | ppl as stated | Delivery | Email needed | Emailed us after? |
|---|---|---|---|---|---|
| Western Fuel | £570.76 (standard); £574.64 (express) | 106.43 / 107.17 | by Mon 19 Oct / by 12 Oct | yes | **yes**: abandoned quote reminder "Still looking for heating oil?" ~4 h later (Klaviyo, sender notice@westernfuel.co.uk) |
| Home Fuels Direct | £577.71 | 110.04 net, no fees | windows up to 19 Oct | no | no (live in KeroTrack) |
| The Heating Oil Company | £587.27 | 111.86 ex VAT | by Mon 19 Oct | yes (plus "how did you hear") | no |
| BoilerJuice | £587.70 (7 Oct); £587.49 (19 Oct) | 109.47 ex VAT + £12.98 service charge | 6 to 19 Oct options | yes | **yes**: full quote email within minutes ("Your heating oil quote", news@e.boilerjuice.com), despite ticking "don't send offers"; footer says the address "agreed to receive Price Alert emails"; quotes valid 30 minutes |
| NWF | £635.62 | 121.07 ex VAT | Standard by Fri 9 Oct, Value by Tue 13 Oct | yes | no |

### The Heating Oil Company (`theheatingoilcompany`): most promising

- Quote is a plain GET whose result page is server rendered HTML:
  `https://www.theheatingoilcompany.co.uk/Quote?productid=10&qty=500&vehicle=4&location=<POSTCODE with + for space>&heardfrom=15&email=<EMAIL>&usage=domestic&getQuote=Get+a+Quote`
  - `productid=10` Standard Domestic Oil (form also offers Premier Oil Cooker / Boiler).
  - `vehicle=4` was the value sent for "Standard" tanker (the other option is Baby Tanker).
  - `heardfrom=15` corresponded to "Google".
- Page text contains, per option: "Delivery on or before Monday, 19 October 2026", "111.86p per litre (exc VAT)", "£587.27 inc VAT"; options seen: "Best Price" and "10 Day Delivery" (same price that day).
- A headless curl **without** `email` and `heardfrom` returned HTTP 500 with an empty body. With them it is expected to work; prove it in the spike.
- The site states quotes can only be ordered on the site.

### NWF Fuels (`nwffuels`)

- Homepage residential form: Fuel Type (`182` Standard Kerosene, `183` Premier Pure Kerosene, `325` Aga/Rayburn), litres, email, postcode, and a **pre ticked** "Keep me updated on exclusive offers" checkbox (must not be sent / must be unticked).
- Submitting navigates to `https://www.nwffuels.co.uk/quote/?postcode=<PC>&email=<EMAIL>&quantity=500&fueltype=MTgy` (`MTgy` = base64 of `182`).
- That page first renders placeholders (`00.00ppl`, `£00.00`) for delivery tiers (Extra Value, Value, Standard, Express, Saturday, Sunday), then fills prices via a **second request not yet captured**. Spike: find that XHR/fetch in Chrome devtools (Network, filter Fetch/XHR) and reproduce it with curl.
- Observed after load: Standard Oil "Standard Delivery" 121.07 ppl ex VAT, £635.62 inc VAT (9 Oct); "Value Delivery" same price (13 Oct). Treat Express / Saturday / Sunday as `urgent=True`; Value / Extra Value / Standard are non urgent.

### Western Fuel (`westernfuel`)

- React single page app at `https://www.westernfuel.co.uk/`. "Get an instant quote" form: Postcode, Litres (quick buttons 500/750/1000/1500), Fuel type (`Kero`, `BetterBurn`, `Betterburn V`), Tanker type (`Standard` = "Standard (6 Wheeler)", `4 Wheeler`, `Baby`), Email address. Results render inline: "STANDARD DELIVERY £570.76 inc. VAT, By Mon 19 Oct, 106.43p/litre · 500 litres" and "EXPRESS DELIVERY £574.64, By Mon 12 Oct, 107.17p/litre".
- The underlying price request was **not** captured: the page repeatedly froze the browser tool's screenshot. Spike: capture with `read_network_requests` / devtools rather than screenshots; look for a JSON API behind the form.
- Note the stated ppl does not reconcile with the total by VAT alone (£570.76 / 1.05 / 500 = 108.72p): there is likely a delivery fee folded in. Always use the total.
- Sends an abandoned quote reminder email after a quote (see table).

### BoilerJuice real quote (`boilerjuice`), optional

- Form on `https://www.boilerjuice.com/uk/heating-oil-quote/`: litres, postcode, email, oil type, tanker, "don't send me offers" checkbox; result at `https://www.boilerjuice.com/uk/journeys/core/quote` (server rendered, multi step journey). Options list each with "Delivery on or before", ppl ex VAT, "You Pay" total including the £12.98 service charge.
- Emails the quote immediately and treats the address as opted in to price alerts regardless of the checkbox. Quotes valid 30 minutes.
- The existing scraper of the national average (`prices/scraper.py`, `prices.boilerjuice_url`) stays as the market index either way. Only add a BoilerJuice *quote* provider if the journey is reproducible with plain HTTP (likely needs a session cookie and CSRF token; drop if not).

### Not pursued

- yournrg: does not deliver to the owner's area (retired).

## Design

### Provider model changes

- `QuoteProvider` gains `requires_email: bool` and an optional `cadence: "frequent" | "daily"` (email requiring providers are `daily`).
- `QuoteRequest` gains `email: str | None`.
- New setting `buying.quote_email_pattern` (string, default `""`, **not** committed with a real value; owner sets e.g. `{site}@<private domain>` in production). Providers with `requires_email` are skipped when it is empty, recorded as an `ok=0` row with `error="no email configured"` only once per day (avoid noise).
- `PROVIDERS` registry adds the new providers by name; `buying.providers` default stays `["homefuelsdirect"]`, the owner enables others in Settings.

### Scheduling

- Keep `schedule.buying_cron` (`0 7,13 * * *`) for the full buying run (quotes from `frequent` providers, index, projection, signal, MQTT).
- New `schedule.buying_daily_quotes_cron` default `30 10 * * *`: polls only `daily` (email) providers, then recomputes the signal and republishes MQTT (no re-projection needed, but it is cheap; reuse `run_buying` with a `providers` filter argument).
- Add the new job name to `scheduler/service.py` `_JOB_TO_SETTING` and `scheduler/jobs.py` `JOB_NAMES`; extend the seam test (`tests/unit/test_scheduler_seam.py`) to assert it fires once per day. Remember the APScheduler gotcha already fixed in this codebase: crontab day `0` means Monday there, so always use day **names**.

### Best quote semantics (important)

With suppliers polled at different times, "cheapest in the latest poll" is wrong (the 13:00 HFD-only poll would hide the 10:30 Western quote). Change `_best_latest` to: **for each supplier, take its most recent ok non urgent quote fetched within 36 h; the best is the cheapest of those.** Apply the same rule to the Buying page's per supplier rows (it already groups per supplier; make it use each supplier's latest poll, not the global latest). `best_recent` (used by `current_ppl`) already spans 36 h and needs no change. Add tests: a cheaper 10:30 daily quote is still the best after a dearer 13:00 frequent poll; a 40 h old quote is ignored.

### Parsing and robustness

- Each provider module: constants for URLs and params, a pure `parse(payload_or_html, litres) -> list[QuoteOption]`, and `fetch(client, req)`. Use BeautifulSoup for HTML (already a dependency, see `prices/scraper.py`).
- Mark express / next day / Saturday / Sunday / emergency options `urgent=True`.
- A changed page shape must yield `[]` plus an error, never a wrong number. Sanity bound: effective ppl between 30 and 300 or discard the option.
- Politeness: honest User-Agent (`USER_AGENT`), one try plus one retry, daily cadence for email providers.

### Fixtures and tests

- Record each supplier's real response once during the spike, then **scrub** postcode, email, names, order or session tokens before committing it under `backend/tests/fixtures/` (pattern: `hfd_quote.json`). respx for HTTP mocking (see `tests/unit/test_quotes_homefuelsdirect.py`).
- Tests per provider: parse happy path (totals, urgent flags, labels), garbage page -> `[]`, HTTP error -> `PollResult.error` without postcode or email (assert the scrub), request carries the email and correct params.

### UI

- Supplier display names: add `theheatingoilcompany` -> "The Heating Oil Company", `nwffuels` -> "NWF Fuels", `westernfuel` -> "Western Fuel" (and `boilerjuice` -> "BoilerJuice" if built) in `frontend/src/lib/buying.ts`.
- Quotes table: show each supplier's quote age (they now differ); daily suppliers will often be up to a day old, which is expected.

## Spike procedure (per supplier, before writing code)

1. In Chrome (the `claude-in-chrome` tools), load the quote page, start `read_network_requests` BEFORE submitting, submit with postcode, 500 L, standard tanker and the supplier's own pattern email; avoid screenshots on Western Fuel (they froze the tool); use `get_page_text` / `find` / `read_network_requests`.
2. Identify the request that returns prices (JSON preferred). Note method, URL, params, headers, cookies.
3. Reproduce with `curl` from the command line (no browser). If it needs only static params: build it. If it needs a session cookie or CSRF token obtainable by one plain GET first: acceptable, document it. If it needs JavaScript execution: drop the supplier and record why in this spec.
4. Record the response as a fixture (scrubbed).

Order: The Heating Oil Company, NWF, Western Fuel, then BoilerJuice quote (optional).

## Process (repo ritual)

- Branch per change; subagent driven development with TDD; reviews per task; final whole branch review.
- Commits must be made from WSL Ubuntu because Windows Application Control blocks the gitleaks binary pre-commit downloads: hooks run via `core.hooksPath=~/kt-hooks` (see the owner's private memory `reference_gitleaks_wsl_commit.md`). Never `--no-verify`.
- Pre-commit blocks RFC 1918 IP literals anywhere outside `docs/`; build such addresses from integers in tests.
- Deploy: push to `main` -> CI builds `ghcr.io/mrsijo/kerotrack-{api,ui}:latest` -> on the docker host `docker stop kerotrack-api`, copy `/dockerdata/kerotrack/data` to `/dockerdata/backups/kerotrack-<ts>` and check `pragma integrity_check`, then `docker --context docker-host compose up -d` from the repo with `compose.override.yaml` present. Verify `/api/health`.
- After deploy: set `buying.quote_email_pattern` in production Settings (private value), add the new providers to `buying.providers`, press "Check prices now" on `/buying` (or wait for 10:30), confirm rows per supplier in `price_quotes`, and check the owner's inbox for any new supplier emails.

## Out of scope

Placing orders; parsing supplier emails (BoilerJuice's quote email could be an alternative data source, but email parsing is fragile); any supplier needing a real browser.
