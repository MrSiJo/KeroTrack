# Changelog

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
