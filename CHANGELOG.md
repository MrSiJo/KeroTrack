# Changelog

## [1.2.0](https://github.com/MrSiJo/KeroTrack/compare/v1.1.0...v1.2.0) (2026-07-08)


### Features

* **ingest:** archive raw Watchman Sonic MQTT payloads ([b834035](https://github.com/MrSiJo/KeroTrack/commit/b8340351d43e48b179d8c519a44001017acedf2c))
* **security:** nginx security headers + XFF hardening (KERO-M5) ([e6a1e47](https://github.com/MrSiJo/KeroTrack/commit/e6a1e47e356670e970353db40b5ee6674be65bcb))
* **security:** rate-limit change-password endpoint (KERO-M5) ([ba89e37](https://github.com/MrSiJo/KeroTrack/commit/ba89e37eb018d4fe604aa60feacfbfe413c2a103))
* **security:** SSRF guard for operator-set URLs (KERO-M5) ([63e0dfd](https://github.com/MrSiJo/KeroTrack/commit/63e0dfdd82a3f4169ee90b70454b854c5376273e))


### Bug Fixes

* aggregate per-reading HDD into daily hdd_data rows (KERO-H1) ([3aae742](https://github.com/MrSiJo/KeroTrack/commit/3aae7428310dc70da6bce65b48caf8b1f1c22999))
* close SettingsService.get cache race (KERO-L3) ([fe7f98c](https://github.com/MrSiJo/KeroTrack/commit/fe7f98cd4838f74b39c3ad298c189628eefd4b11))
* **deps:** bump frontend deps to clear Dependabot alerts ([bac051a](https://github.com/MrSiJo/KeroTrack/commit/bac051a58608a9d844fd635264a953b499de54ff))
* document real rate-limit keying; expose FORWARDED_ALLOW_IPS knob (KERO-H2) ([d1f3c8f](https://github.com/MrSiJo/KeroTrack/commit/d1f3c8f4cb33465ce8997b397cc5b5d16a1dc7f5))
* **ingest:** suppress refill/leak flags on Watchman Sonic multipath misreads ([e29098e](https://github.com/MrSiJo/KeroTrack/commit/e29098ea12c71e4d3658e1be285c6d44cc6a5ba7))
* move blocking notify and DNS lookups off the event loop (KERO-M1) ([90d702e](https://github.com/MrSiJo/KeroTrack/commit/90d702e20b0c71cff532bdedd79ba3f24fd9b7af))
* name detect_refill's air-gap threshold (KERO-L7) ([136939d](https://github.com/MrSiJo/KeroTrack/commit/136939d8b39e62d10fa4ed918ada890900a60395))
* **noise:** catch 60min+jitter spikes, drop noisy rows from walkers, clean orphan periods ([cf2b13b](https://github.com/MrSiJo/KeroTrack/commit/cf2b13b6e54e43dfcf4944054ae90b57f69f31e3))
* **noise:** chain through suppressed rows so multi-reading drifts get marked ([58af3c2](https://github.com/MrSiJo/KeroTrack/commit/58af3c2eddc8e4622648aa73401ef512fedbc850))
* **noise:** direction-aware sanity gate + manual-log refill anchor ([a2d9974](https://github.com/MrSiJo/KeroTrack/commit/a2d9974bb524e6af41a9bc0d6c51906fbd8fb594))
* **noise:** keep sanity bound active across chain-noise gaps ([9785a37](https://github.com/MrSiJo/KeroTrack/commit/9785a37893ca7e83fb8d34b9f27108fc9af8318e))
* **noise:** order analysis_results by latest_analysis_date, not latest_reading_date ([56e1da9](https://github.com/MrSiJo/KeroTrack/commit/56e1da9160aa7fa8b5326e332e21eb8689998eb8))
* **noise:** skip noise_suppressed rows when picking 'latest reading' ([650016b](https://github.com/MrSiJo/KeroTrack/commit/650016bb5be7334b4eb90fd30a62518b159ccfd7))
* pin backend deps via constraints; cache Docker dep layer (KERO-M4) ([91e2bb7](https://github.com/MrSiJo/KeroTrack/commit/91e2bb7e282b4c991e87e0bce65e2aadbbb54d8c))
* price-fetch failure cooldown; derive cache path from DB dir (KERO-M3) ([7c34a68](https://github.com/MrSiJo/KeroTrack/commit/7c34a686f35cf8f600f5def02ad9b202db20347e))
* raw-capture retention sweep; upsert cost_analysis per day (KERO-L5) ([9a667fd](https://github.com/MrSiJo/KeroTrack/commit/9a667fd8036687db7d17f63770566d03c67cfec2))
* real source for upcoming_month_hdd (KERO-L8) ([3bbd22d](https://github.com/MrSiJo/KeroTrack/commit/3bbd22df41c1ae1291cc06c63ae08ed679ec6744))
* remove dead code (KERO-L1) ([6708f42](https://github.com/MrSiJo/KeroTrack/commit/6708f420c2502ca823bf42eed8ee2cd3e6870b10))
* return 503 from /api/health when degraded (KERO-M2) ([6bb371d](https://github.com/MrSiJo/KeroTrack/commit/6bb371df30204e22f8a9e6f46393344128ec60a5))
* share ECharts lifecycle via useEchart helper (KERO-L4) ([04d6a99](https://github.com/MrSiJo/KeroTrack/commit/04d6a99379f5d9b21442a4639aa13746d9a85b3b))
* share trusted-readings clause across analysis and notifier (KERO-H3) ([97415a3](https://github.com/MrSiJo/KeroTrack/commit/97415a3389bba5f51f917e3bc40bde35c3fb1271))
* single pytest config, drop stale warning filters (KERO-L2) ([5eeac04](https://github.com/MrSiJo/KeroTrack/commit/5eeac04e69551dc0a7c09da0703a784a990008d4))
* UI healthcheck probes 127.0.0.1 instead of localhost ([a2f7c75](https://github.com/MrSiJo/KeroTrack/commit/a2f7c75988b0fecc7b23fdadeb6350c63264a9f5))
* validate refill_date as YYYY-MM-DD HH:MM:SS at entry (KERO-L6) ([e09909b](https://github.com/MrSiJo/KeroTrack/commit/e09909b653f15e16c6c5496b4c02f2ef63d2e14a))

## [1.1.0](https://github.com/MrSiJo/KeroTrack/compare/v1.0.1...v1.1.0) (2026-05-09)


### Features

* **mqtt:** add topic_readings_publish setting + LilyGO-shaped subscribe default ([e7b4c03](https://github.com/MrSiJo/KeroTrack/commit/e7b4c036671e0bdf85defe70426f9f67a6bcca6e))

## [1.0.1](https://github.com/MrSiJo/KeroTrack/compare/v1.0.0...v1.0.1) (2026-05-09)


### Bug Fixes

* **ci:** drop paths-ignore from build-images so tag pushes always trigger ([f357d2d](https://github.com/MrSiJo/KeroTrack/commit/f357d2d2eeb443cad9e9d1e429328f55b0598e3a))

## 1.0.0 (2026-05-09)


### Features

* **auth:** Phase 2.5 — argon2id session-cookie auth + security hardening ([3138b64](https://github.com/MrSiJo/KeroTrack/commit/3138b645e2a2e5842d75b5ce3ed8a7cdb4d68e4e))
* **ui:** post-setup onboarding wizard — MQTT, tank, boiler ([b1a0362](https://github.com/MrSiJo/KeroTrack/commit/b1a0362e79d9328d0f935f6c18fda8dda5d2763f))
* **ui:** Records page filter bar — date range + litres/%/used/temp/refill/leak ([e30b070](https://github.com/MrSiJo/KeroTrack/commit/e30b0706a3da49221170ac4c2ceb5a430313361f))


### Bug Fixes

* avg_daily uses simple 7-day delta (not per-pair walker sum) ([bc64d8a](https://github.com/MrSiJo/KeroTrack/commit/bc64d8a09030cbbbb8ced2149dd8734cd3e36dff))
* cost.py per-pair walker also uses net × time-weighted PPL ([60e02dc](https://github.com/MrSiJo/KeroTrack/commit/60e02dce1d7d50816f60fdbf9476b7fe529f9313))
* trends 90d/365d 422, forecast horizon clip, hw-split label ([e74d762](https://github.com/MrSiJo/KeroTrack/commit/e74d76210c01b880942b0c7d03aefaa2c79271f1))
* trends/costs/forecast chart data windows + math ([b0c0b17](https://github.com/MrSiJo/KeroTrack/commit/b0c0b1774ee171ccf93a2596f8b9b5d028625c7b))
* **ui:** TankHeroPanel — tank/bars wrapper width + cost-to-fill string coercion ([9d72dfb](https://github.com/MrSiJo/KeroTrack/commit/9d72dfb06157a2e3a502332be112ad62e286b050))
* **ui:** tighten first-run wizard so a fresh deploy doesn't trip on stale defaults ([f250ad3](https://github.com/MrSiJo/KeroTrack/commit/f250ad35195074d36df85535207c0f13fc631d35))
* **ui:** Trends loadYear uses desc order so the heatmap shows recent months ([982356d](https://github.com/MrSiJo/KeroTrack/commit/982356df7164ee47320bdfbe4fa32e6a55393419))
