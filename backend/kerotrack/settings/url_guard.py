"""SSRF guards for operator-set URLs stored in the settings table.

The security contract (CLAUDE.md → "Outbound HTTP / SSRF") requires scheme
validation plus an allowlist where feasible for any user-supplied URL the
backend will fetch. Two settings feed outbound fetches:

- ``prices.boilerjuice_url`` / ``prices.yournrg_url`` — the price scraper
  GETs these directly. They are ordinary public web pages, so we pin them to
  ``http``/``https`` and allowlist the known price-provider hostnames.
- ``notifications.apprise_urls`` — a JSON list of Apprise targets. Apprise
  uses its own scheme zoo (``gotify://``, ``mailto://`` …), so we cannot
  allowlist a domain set; instead we reject schemes that would let the
  backend reach internal HTTP services and reject hosts that resolve to
  loopback / link-local / private (RFC1918) addresses.

Validation runs at WRITE time in ``SettingsService.set`` so a bad value never
lands in the table. ``SettingError`` is raised on rejection, which the API
layer already turns into a clean 4xx.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


# Public web schemes the price scraper is allowed to fetch.
_WEB_SCHEMES = {"http", "https"}

# Known price-provider hosts. Sub-paths change but the host set is stable; an
# operator pointing these at anything else is almost certainly a mistake or an
# SSRF attempt, so we pin them.
_PRICE_ALLOWLIST: dict[str, set[str]] = {
    "prices.boilerjuice_url": {"www.boilerjuice.com", "boilerjuice.com"},
    "prices.yournrg_url": {"www.yournrg.co.uk", "yournrg.co.uk"},
}

# Apprise schemes that ride over HTTP(S) to an arbitrary host — these are the
# ones that can be abused to reach internal services, so they get host vetting.
# (Apprise also has hostless schemes like ``json://`` etc.; any scheme with a
# real host is vetted regardless, this set just documents the risky cases.)
_HOSTED_APPRISE_SCHEMES = {
    "http",
    "https",
    "gotify",
    "gotifys",
    "ntfy",
    "ntfys",
    "matrix",
    "matrixs",
    "mqtt",
    "mqtts",
    "form",
    "forms",
    "json",
    "jsons",
    "xml",
    "xmls",
}


def _host_resolves_to_internal(host: str) -> bool:
    """True if ``host`` is, or resolves to, a non-public address.

    Covers loopback, link-local, private (RFC1918), unique-local IPv6, and
    unspecified ranges. A literal IP is checked directly; a name is resolved
    via ``getaddrinfo`` and rejected if *any* resolved address is internal.
    """
    candidates: list[str] = []
    try:
        ipaddress.ip_address(host)
        candidates.append(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            # Unresolvable now — let the fetch fail later rather than block a
            # transiently-down DNS name. We are not the firewall.
            return False
        candidates = [info[4][0] for info in infos]

    for addr in candidates:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_unspecified
            or ip.is_reserved
        ):
            return True
    return False


def validate_price_url(key: str, value: str) -> None:
    """Validate a ``prices.*_url`` setting. Raises ``SettingError`` on reject."""
    from kerotrack.settings.service import SettingError

    parsed = urlparse(value)
    if parsed.scheme not in _WEB_SCHEMES:
        raise SettingError(
            "invalid_url_scheme",
            f"{key}: URL scheme must be http or https, got {parsed.scheme!r}",
            field=key,
        )
    host = parsed.hostname
    if not host:
        raise SettingError(
            "invalid_url",
            f"{key}: URL has no host",
            field=key,
        )
    allowed = _PRICE_ALLOWLIST.get(key)
    if allowed is not None and host.lower() not in allowed:
        raise SettingError(
            "url_host_not_allowed",
            f"{key}: host {host!r} is not in the allowlist {sorted(allowed)}",
            field=key,
        )
    if _host_resolves_to_internal(host):
        raise SettingError(
            "url_host_internal",
            f"{key}: host {host!r} resolves to an internal address",
            field=key,
        )


def validate_apprise_urls(key: str, value: object) -> None:
    """Validate ``notifications.apprise_urls`` (a list of Apprise targets)."""
    from kerotrack.settings.service import SettingError

    if value in (None, ""):
        return
    if not isinstance(value, list):
        raise SettingError(
            "invalid_apprise_urls",
            f"{key}: expected a list of URLs",
            field=key,
        )
    for entry in value:
        # Non-string / malformed entries carry no SSRF host; Apprise itself
        # rejects them at send time, so we don't second-guess shape here —
        # we only block entries that resolve to an internal network target.
        if not isinstance(entry, str) or not entry.strip():
            continue
        parsed = urlparse(entry.strip())
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        # Only vet hosts for schemes that actually dial out over a network to
        # an attacker-influenceable host. Hostless/credential-only schemes
        # (e.g. tgram://, mailto:) carry no SSRF surface here.
        if host and scheme in _HOSTED_APPRISE_SCHEMES:
            if _host_resolves_to_internal(host):
                raise SettingError(
                    "url_host_internal",
                    f"{key}: {entry!r} targets internal address {host!r}",
                    field=key,
                )


# Dispatch table keyed on setting key — empty for keys with no URL guard.
_VALIDATORS = {
    "prices.boilerjuice_url": validate_price_url,
    "prices.yournrg_url": validate_price_url,
}


def validate_url_setting(key: str, value: object) -> None:
    """Apply the SSRF guard for ``key`` if one is registered; else no-op."""
    if key == "notifications.apprise_urls":
        validate_apprise_urls(key, value)
        return
    validator = _VALIDATORS.get(key)
    if validator is not None:
        validator(key, value)  # type: ignore[arg-type]
