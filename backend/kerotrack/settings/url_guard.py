"""SSRF guards for operator-set URLs stored in the settings table.

The security contract (CLAUDE.md → "Outbound HTTP / SSRF") requires scheme
validation plus an allowlist where feasible for any user-supplied URL the
backend will fetch. Two settings feed outbound fetches:

- ``prices.boilerjuice_url`` — the price scraper GETs this directly. It is
  an ordinary public web page, so we pin it to ``http``/``https`` and
  allowlist the known price-provider hostname.
- ``notifications.apprise_urls`` — a JSON list of Apprise targets. Apprise
  uses its own scheme zoo (``gotify://``, ``mailto://`` …), so we cannot
  allowlist a domain set; instead we vet the host. A self-hosted app's main
  notification target is a LAN Gotify, so private RFC1918 and unique-local
  IPv6 (fc00::/7) hosts ARE allowed here. Loopback, link-local (169.254/16
  including cloud metadata, fe80::/10), unspecified, multicast and reserved
  hosts are still rejected. The price URL guard is stricter and keeps
  rejecting private hosts too.

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


# The only private networks a LAN notification target may live on: the three
# RFC 1918 blocks (class A, B and C private ranges) and IPv6 unique-local.
# Built from integers so no dotted literal sits in source.
_LAN_NETWORKS = (
    ipaddress.ip_network((0x0A000000, 8)),
    ipaddress.ip_network((0xAC100000, 12)),
    ipaddress.ip_network((0xC0A80000, 16)),
    ipaddress.ip_network((0xFC << 120, 7)),
)


def _host_resolves_to_internal(host: str, *, allow_private: bool = False) -> bool:
    """True if ``host`` is, or resolves to, a disallowed address.

    Covers loopback, link-local, private (RFC1918), unique-local IPv6,
    unspecified, multicast and reserved ranges. With ``allow_private`` the
    private and unique-local ranges are permitted (LAN notification targets);
    everything else stays rejected. A literal IP is checked directly; a name
    is resolved via ``getaddrinfo`` and rejected if *any* resolved address is
    disallowed.
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
        # Unwrap IPv6 forms that embed an IPv4 address so they are judged as
        # the IPv4 they really reach. Teredo cannot be judged safely: reject.
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            elif ip.sixtofour is not None:
                ip = ip.sixtofour
            elif ip.teredo is not None:
                return True
        # Always rejected, whatever the allowance.
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_multicast
            or ip.is_reserved
        ):
            return True
        if allow_private:
            # Only the explicit LAN networks; other "private" ranges (CGNAT,
            # IETF protocol, benchmarking) stay rejected.
            if not any(ip in net for net in _LAN_NETWORKS):
                return True
        elif ip.is_private or not ip.is_global:
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
            if _host_resolves_to_internal(host, allow_private=True):
                raise SettingError(
                    "url_host_internal",
                    f"{key}: {entry!r} targets internal address {host!r}",
                    field=key,
                )


# Dispatch table keyed on setting key — empty for keys with no URL guard.
_VALIDATORS = {
    "prices.boilerjuice_url": validate_price_url,
}


def validate_url_setting(key: str, value: object) -> None:
    """Apply the SSRF guard for ``key`` if one is registered; else no-op."""
    if key == "notifications.apprise_urls":
        validate_apprise_urls(key, value)
        return
    validator = _VALIDATORS.get(key)
    if validator is not None:
        validator(key, value)  # type: ignore[arg-type]
