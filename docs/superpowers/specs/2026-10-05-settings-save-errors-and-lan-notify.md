# Settings: surface rejected saves; allow LAN notification targets

**Status:** Approved by the owner 2026-10-05.

## Problem

1. `PUT /api/settings` (bulk) returns HTTP 200 with `{"saved": [...], "errors": [...]}` when some keys are rejected. The frontend `settings.save()` (`frontend/src/lib/stores/settings.ts`) ignores `errors`, so the Settings page shows "Saved" while nothing was stored. Onboarding uses the same call. The owner hit this saving a new Gotify token.
2. `settings/url_guard.py` rejects any Apprise target whose host resolves to a private (RFC 1918) address. A self-hosted app's main notification target is a LAN Gotify, so notifications cannot be configured at all.

## Changes

1. **Surface errors.** `settings.save()` (and onboarding) treats a non-empty `errors` list as a failure: the saved keys are applied, the failed keys stay pending with their messages, and the page shows an error naming each failed setting by label, e.g. "Not saved: Apprise URLs (targets internal address ...)". "Saved" only appears when every key saved. The per-key error message is shown next to the field in SettingsForm too.
2. **LAN notification targets allowed.** For `notifications.apprise_urls` only, private RFC 1918 and unique-local IPv6 (fc00::/7) hosts are allowed. Still rejected: loopback, link-local (169.254.0.0/16 incl. cloud metadata, fe80::/10), unspecified, multicast, reserved. The price URL guard is unchanged (it keeps rejecting private hosts). Update the module docstring and the security-invariants tests: keep a test that loopback and 169.254.169.254 are rejected; add one that a 172.16.x Gotify target is accepted.

## Out of scope

Changing the bulk endpoint's 200 contract (other clients may rely on it).
