"""Async client for the xcrawl web-data API (search / scrape).

xcrawl turns "the LLM guessed a URL" into "real fetched content". The
watchlist uses it to monitor sources that have NO usable RSS feed —
modern JS-rendered / bot-blocked marketing + news pages the keyless RSS
adapter cannot read — via scrape-backed change detection, and to
validate / repair a feed target at insert time so dead rows never reach
the scan loop.

``search`` (SERP) is also exposed for callers that need keyword
discovery rather than a known URL.

Posture mirrors ``memory.honcho_client``: settings-gated, timeout-
bounded, graceful degradation (every failure returns an empty result,
never raises into the caller), and one audit row per call. No SSRF guard
is needed here: the ``url`` argument may be caller- or LLM-supplied (e.g.
the research ``scrape_url`` tool), but it is sent as a JSON payload field
and fetched on xcrawl's network — our process only ever connects to the
configured xcrawl base URL, never to the target.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, NamedTuple

import httpx
from pydantic import BaseModel

from openexecutive.audit import log_event as audit_log
from openexecutive.config import get_settings

logger = logging.getLogger(__name__)

# Max chars of the query / url recorded in an audit row's subject_preview.
_AUDIT_SUBJECT_PREVIEW_CHARS = 160
# SERP result count: default, and xcrawl's documented 1–100 ceiling.
_DEFAULT_SEARCH_LIMIT = 5
_MAX_SEARCH_LIMIT = 100


class SearchResult(BaseModel):
    """One SERP row, normalized from xcrawl's response envelope."""

    title: str
    url: str
    snippet: str


def _resolve_credentials() -> tuple[bool, str | None]:
    """Return ``(enabled, api_key)``.

    "Enabled" requires the flag AND a non-empty key. A flag set without a
    key degrades to disabled (with a warning) rather than letting a
    keyless request 401 on every call — and deliberately there is no
    config-level "required when enabled" validator that would crash boot.
    """
    settings = get_settings()
    if not settings.xcrawl_enabled:
        return False, None
    key = (settings.xcrawl_api_key or "").strip()
    if not key:
        logger.warning(
            "xcrawl: XCRAWL_ENABLED is true but XCRAWL_API_KEY is unset — "
            "treating xcrawl as disabled",
        )
        return False, None
    return True, key


async def _post_json(endpoint: str, key: str, payload: dict[str, Any]) -> Any:
    """POST ``payload`` to an xcrawl endpoint and return the parsed JSON.

    ``raise_for_status`` and ``.json()`` run INSIDE the client context so
    the response body is always read before the connection closes. Raises
    on any transport / HTTP-status / decode error; callers own the
    op-specific logging + audit + graceful-degradation.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.xcrawl_timeout_s) as client:
        resp = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


def _endpoint(path: str) -> str:
    return f"{get_settings().xcrawl_base_url.rstrip('/')}/{path}"


async def search(
    query: str, *, limit: int = _DEFAULT_SEARCH_LIMIT,
) -> list[SearchResult]:
    """Run one SERP query against xcrawl ``/search``.

    Returns the ranked results, or ``[]`` when xcrawl is disabled, the
    query is blank, or the call fails. Never raises — a research run must
    not abort because xcrawl is unavailable.
    """
    query = (query or "").strip()
    if not query or limit <= 0:
        # limit<=0 means "no results wanted" — return without charging xcrawl.
        return []
    enabled, key = _resolve_credentials()
    if not enabled or key is None:
        return []

    # Clamp to xcrawl's documented ceiling (floor already handled above).
    bounded_limit = min(limit, _MAX_SEARCH_LIMIT)
    payload = {"query": query, "limit": bounded_limit}
    try:
        body = await _post_json(_endpoint("search"), key, payload)
    except Exception as exc:
        logger.warning("xcrawl: search failed for %r: %s", query[:80], exc)
        _audit("search", query, ok=False, count=0, error=str(exc)[:200])
        return []

    results = _parse_search(body)
    _audit(
        "search", query, ok=True, count=len(results),
        credits=body.get("total_credits_used") if isinstance(body, dict) else None,
    )
    return results[:bounded_limit]


ScrapeStatus = Literal["ok", "empty", "error", "disabled"]


class ScrapeOutcome(NamedTuple):
    """Result of a scrape attempt, distinguishing *why* there is no markdown.

    ``status`` lets a caller tell an infra failure apart from a page that was
    fetched but yields nothing — a distinction ``scrape``'s bare ``None``
    cannot make:

      - ``"ok"``       — markdown retrieved (``markdown`` is non-None)
      - ``"empty"``    — fetched OK but no usable markdown (genuinely dead /
                         empty page — the page's fault)
      - ``"error"``    — the request failed (transport / HTTP status / decode):
                         transient infra (xcrawl down, 401, 429, timeout), NOT
                         a verdict on the page. Callers that penalise a dead
                         source must treat this as "couldn't check", not "dead".
      - ``"disabled"`` — xcrawl off / no key / blank url; no call was made.

    ``markdown`` is non-None only for ``status == "ok"``.
    """

    markdown: str | None
    status: ScrapeStatus


async def scrape_detailed(url: str) -> ScrapeOutcome:
    """Fetch ``url`` via xcrawl ``/scrape`` and return a status-tagged result.

    xcrawl renders JS and fetches through a residential proxy, so it reads
    pages the keyless httpx fetcher cannot (JS-only SPAs, soft bot blocks)
    — the basis for monitoring sources that publish no RSS feed.

    Never raises — the status carries the failure mode (see ``ScrapeOutcome``).
    """
    url = (url or "").strip()
    if not url:
        return ScrapeOutcome(None, "disabled")
    enabled, key = _resolve_credentials()
    if not enabled or key is None:
        return ScrapeOutcome(None, "disabled")

    payload = {
        "url": url,
        "output": {"formats": ["markdown"]},
        "request": {"only_main_content": True},
    }
    try:
        body = await _post_json(_endpoint("scrape"), key, payload)
    except Exception as exc:
        # Transport / HTTP-status / decode failure — xcrawl itself misbehaved.
        # This is infra, not a verdict on the page.
        logger.warning("xcrawl: scrape failed for %r: %s", url[:80], exc)
        _audit("scrape", url, ok=False, count=0, error=str(exc)[:200])
        return ScrapeOutcome(None, "error")

    markdown = _parse_scrape(body)
    if markdown is not None:
        # Bound the markdown to mirror the keyless path's byte cap so a
        # giant page can't blow up the downstream hash / diff / storage on
        # the scan worker. (chars ≈ bytes for the latin-heavy markdown we
        # store; an exact byte cap isn't needed for this DoS guard.)
        max_chars = get_settings().external_monitor_max_fetch_bytes
        if len(markdown) > max_chars:
            logger.info(
                "xcrawl: scrape markdown for %r truncated %d→%d chars",
                url[:80], len(markdown), max_chars,
            )
            markdown = markdown[:max_chars]
    _audit(
        "scrape", url, ok=markdown is not None,
        count=1 if markdown else 0,
        credits=body.get("total_credits_used") if isinstance(body, dict) else None,
    )
    return ScrapeOutcome(markdown, "ok" if markdown is not None else "empty")


async def scrape(url: str) -> str | None:
    """Fetch ``url`` via xcrawl ``/scrape`` and return cleaned markdown.

    Returns ``None`` when xcrawl is disabled, the url is blank, the call
    fails, or the page yields no markdown. Never raises — callers treat
    ``None`` as "no fetch this tick". Callers that must distinguish an infra
    failure from a genuinely empty/dead page use ``scrape_detailed`` instead.
    """
    return (await scrape_detailed(url)).markdown


def _parse_scrape(body: dict[str, Any]) -> str | None:
    """Pull markdown out of xcrawl's scrape envelope: ``{"data": {"markdown": ...}}``.

    Tolerates one extra level of nesting (``data.data.markdown``) and
    treats blank / whitespace-only markdown as "no content" (``None``).
    """
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    for candidate in (data, data.get("data")):
        if isinstance(candidate, dict):
            md = candidate.get("markdown")
            if isinstance(md, str) and md.strip():
                return md
    return None


def _parse_search(body: dict[str, Any]) -> list[SearchResult]:
    """Pull the result rows out of xcrawl's nested response envelope.

    The live shape is ``{"data": {"data": [ {position, title,
    description, url}, ... ]}}``. We tolerate the inner list living at
    either ``data`` or ``data.data`` (shape-drift defence) and skip any
    row missing a usable URL.
    """
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    inner: Any = None
    if isinstance(data, dict):
        inner = data.get("data")
    elif isinstance(data, list):
        inner = data
    if not isinstance(inner, list):
        return []

    out: list[SearchResult] = []
    for row in inner:
        if not isinstance(row, dict):
            continue
        result_url = (row.get("url") or row.get("link") or "").strip()
        if not result_url:
            continue
        out.append(
            SearchResult(
                title=(row.get("title") or "").strip(),
                url=result_url,
                snippet=(row.get("description") or row.get("snippet") or "").strip(),
            )
        )
    return out


def _audit(
    op: str,
    subject: str,
    *,
    ok: bool,
    count: int,
    credits: Any = None,
    error: str | None = None,
) -> None:
    """Write one ``xcrawl`` audit row so spend + failures are visible.

    ``subject`` is the query (search) or the url (scrape).
    """
    details: dict[str, Any] = {
        "op": op,
        "subject_preview": subject[:_AUDIT_SUBJECT_PREVIEW_CHARS],
        "result_count": count,
        "ok": ok,
    }
    if credits is not None:
        details["credits_used"] = credits
    if error:
        details["error"] = error
    audit_log(
        "xcrawl",
        f"xcrawl.{op}: results={count} ok={ok}",
        actor="xcrawl",
        details=details,
    )


__all__ = [
    "ScrapeOutcome",
    "ScrapeStatus",
    "SearchResult",
    "scrape",
    "scrape_detailed",
    "search",
]
