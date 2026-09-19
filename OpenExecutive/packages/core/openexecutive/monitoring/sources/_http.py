"""Shared HTTP + URL safety helpers for monitoring source adapters.

Every adapter that hits an external URL goes through these helpers so
the SSRF guard, body-size cap, redirect cap, and query-string strip are
applied once and consistently. New adapters MUST NOT use ``httpx``
directly — call :func:`fetch_bounded` instead.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# Schemes a watchlist target is allowed to use. Excludes file://, ftp://,
# data:, javascript:, etc. so a misconfigured row can't read local files
# or invoke unexpected protocol handlers.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Tight redirect cap — a malicious feed shouldn't be able to pull
# megabytes of data via a long 30x chain. Three is enough for any real
# CDN setup without giving the attacker enough rope.
MAX_REDIRECTS = 3

HTTP_TIMEOUT_SECONDS = 15.0

# Neutral identifier — some Statuspage / news / stock APIs 403 the
# default httpx UA. Including a project URL would let upstream contact
# us about rate-limiting; intentionally omitted to avoid tenant leak.
USER_AGENT = "OpenExecutive-Monitor/1.0"


class FetchOverflowError(Exception):
    """Raised when a fetched body exceeded the configured byte ceiling."""


def validate_target_url(url: str) -> tuple[bool, str]:
    """SSRF guard: only allow public http(s) URLs.

    Rejects non-http(s) schemes and any host that resolves to a
    loopback / link-local / private / reserved IP — the classic SSRF
    pivots into IMDS (169.254.169.254), local services (127.*), or
    private cloud meshes (RFC1918, Fly fdaa::/64). Returns
    ``(False, reason)`` to be logged at the call site.

    First-resolution check only — full DNS-rebind defence would need
    re-resolution at fetch time. For the watchlist threat model
    (misconfigured row, not a remote attacker timing DNS) this is a
    strong perimeter.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, f"unparseable URL: {exc}"
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return False, f"scheme {scheme!r} not in {sorted(ALLOWED_SCHEMES)}"
    host = parsed.hostname or ""
    if not host:
        return False, "URL has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed: {exc}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"host {host!r} resolves to non-public IP {ip}"
    return True, ""


def strip_url_query(url: str) -> str:
    """Drop the query string + fragment from a URL.

    Feeds occasionally embed analytics tokens (``?utm_source=…``) or
    session identifiers on links; a malicious feed could push arbitrary
    ``?token=<value>`` query strings into our audit log and DM bodies.
    Strip on the way in — the canonical path stays clickable.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    return parsed._replace(query="", fragment="").geturl()


async def fetch_bounded(
    url: str, max_bytes: int, *, user_agent: str | None = None
) -> bytes:
    """GET ``url`` with a body-size ceiling and tight redirect cap.

    Streams the response and stops once the cumulative read exceeds
    ``max_bytes`` so a malicious feed cannot exhaust memory. Raises
    :class:`FetchOverflowError` rather than truncating-and-pretending-
    it-worked so the caller can log + skip the tick honestly.

    ``user_agent`` overrides the default UA for hosts that require a
    specific identifier — e.g. SEC EDGAR rejects/ratelimits the generic
    UA and asks callers to identify with a contact. Falls back to the
    module ``USER_AGENT`` when None.
    """
    transport = httpx.AsyncHTTPTransport(retries=0)
    async with (
        httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            transport=transport,
            headers={"User-Agent": user_agent or USER_AGENT},
        ) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise FetchOverflowError()
        return bytes(buf)


__all__ = [
    "ALLOWED_SCHEMES",
    "FetchOverflowError",
    "HTTP_TIMEOUT_SECONDS",
    "MAX_REDIRECTS",
    "USER_AGENT",
    "fetch_bounded",
    "strip_url_query",
    "validate_target_url",
]
