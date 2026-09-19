"""Unit tests for insert-time watchlist target validation.

Covers: non-rss passthrough (no network), valid-feed keep, non-feed →
page_watch conversion, non-feed-non-scrapeable reject, transient-failure
keep, and the 4xx → reject path. All network is mocked.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from openexecutive.monitoring import target_validation as tv
from openexecutive.monitoring.models import (
    PAGE_WATCH_FETCH_KEY,
    PAGE_WATCH_FETCH_XCRAWL,
)
from openexecutive.monitoring.sources import page_watch
from openexecutive.monitoring.sources._http import FetchOverflowError

_FEED = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
    b"<item><title>i1</title><link>http://x/1</link><guid>1</guid></item>"
    b"</channel></rss>"
)
# Valid RSS that is recognized as a feed but currently has no <item> entries.
_EMPTY_FEED = (
    b'<?xml version="1.0"?><rss version="2.0"><channel>'
    b"<title>Brand new feed</title></channel></rss>"
)
_NOT_FEED = b"<html><body><h1>Pricing</h1><p>not a feed</p></body></html>"


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fetch: Any,
    scrape_result: str | None = None,
) -> None:
    monkeypatch.setattr(tv, "validate_target_url", lambda u: (True, ""))
    monkeypatch.setattr(tv, "fetch_bounded", fetch)

    async def fake_scrape(url: str) -> str | None:
        return scrape_result

    monkeypatch.setattr(
        "openexecutive.integrations.xcrawl_client.scrape", fake_scrape,
    )


def _fetch_returning(body: bytes) -> Any:
    async def _f(url: str, max_bytes: int, **kw: object) -> bytes:
        return body
    return _f


def _fetch_raising(exc: Exception) -> Any:
    async def _f(url: str, max_bytes: int, **kw: object) -> bytes:
        raise exc
    return _f


@pytest.mark.asyncio
async def test_non_rss_passthrough_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # fetch_bounded set to explode — a stock add must never touch it.
    async def boom(*a: object, **k: object) -> bytes:
        raise AssertionError("non-rss must not fetch")

    monkeypatch.setattr(tv, "fetch_bounded", boom)
    st, target, config = await tv.validate_and_normalize_target(
        "stock", "AAPL", {"display_name": "Apple"},
    )
    assert (st, target, config) == ("stock", "AAPL", {"display_name": "Apple"})


@pytest.mark.asyncio
async def test_valid_feed_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, fetch=_fetch_returning(_FEED))
    st, target, config = await tv.validate_and_normalize_target(
        "rss", "https://good.example/feed", {"feed_label": "Good"},
    )
    assert st == "rss"
    assert config == {"feed_label": "Good"}


@pytest.mark.asyncio
async def test_non_feed_scrapeable_converts_to_page_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch, fetch=_fetch_returning(_NOT_FEED),
        scrape_result="# Pricing\n\ncontent",
    )
    st, target, config = await tv.validate_and_normalize_target(
        "rss", "https://news.example/page", {"feed_label": "News"},
    )
    assert st == page_watch.PageWatchSource.kind  # "page_watch"
    # Drift guard: the conversion must match the shared xcrawl sentinel that
    # page_watch reads (both key and value).
    assert config[PAGE_WATCH_FETCH_KEY] == PAGE_WATCH_FETCH_XCRAWL
    # feed_label is remapped to the label key page_watch reads.
    assert config.get("label") == "News"
    assert "feed_label" not in config


@pytest.mark.asyncio
async def test_empty_but_valid_feed_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A recognized feed with zero entries (brand-new / quiet) must be kept as
    # rss, not misread as a non-feed page.
    _install(monkeypatch, fetch=_fetch_returning(_EMPTY_FEED))
    st, _t, config = await tv.validate_and_normalize_target(
        "rss", "https://new.example/feed", {},
    )
    assert st == "rss"


@pytest.mark.asyncio
async def test_empty_body_is_not_feed_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HTTP 200 with a zero-byte body: feedparser yields a dict with no
    # `version` key — must classify as not_feed, not raise AttributeError.
    _install(monkeypatch, fetch=_fetch_returning(b""), scrape_result=None)
    with pytest.raises(tv.WatchlistTargetError):
        await tv.validate_and_normalize_target("rss", "https://empty.example", {})


@pytest.mark.asyncio
async def test_non_feed_not_scrapeable_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, fetch=_fetch_returning(_NOT_FEED), scrape_result=None)
    with pytest.raises(tv.WatchlistTargetError) as ei:
        await tv.validate_and_normalize_target(
            "rss", "https://dead.example/x", {},
        )
    assert "not a valid RSS" in str(ei.value)


@pytest.mark.asyncio
async def test_404_status_is_not_feed_then_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = httpx.HTTPStatusError(
        "404",
        request=httpx.Request("GET", "https://x.example"),
        response=httpx.Response(404),
    )
    _install(monkeypatch, fetch=_fetch_raising(exc), scrape_result=None)
    with pytest.raises(tv.WatchlistTargetError):
        await tv.validate_and_normalize_target("rss", "https://x.example", {})


@pytest.mark.asyncio
async def test_transient_failure_keeps_rss_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, fetch=_fetch_raising(httpx.ConnectError("reset")))
    st, target, config = await tv.validate_and_normalize_target(
        "rss", "https://maybe.example/feed", {},
    )
    assert st == "rss"  # not penalized for a transient blip


@pytest.mark.asyncio
async def test_oversized_body_is_not_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch, fetch=_fetch_raising(FetchOverflowError()),
        scrape_result=None,
    )
    with pytest.raises(tv.WatchlistTargetError):
        await tv.validate_and_normalize_target("rss", "https://big.example", {})


@pytest.mark.asyncio
async def test_ssrf_rejected_target_is_not_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tv, "validate_target_url", lambda u: (False, "private IP"))

    async def boom(*a: object, **k: object) -> bytes:
        raise AssertionError("must not fetch an SSRF-rejected target")

    async def boom_scrape(url: str) -> str | None:
        raise AssertionError("must not hand an SSRF-rejected target to xcrawl")

    monkeypatch.setattr(tv, "fetch_bounded", boom)
    monkeypatch.setattr(
        "openexecutive.integrations.xcrawl_client.scrape", boom_scrape,
    )
    # Rejected outright as "blocked" — neither fetched locally nor scraped.
    with pytest.raises(tv.WatchlistTargetError):
        await tv.validate_and_normalize_target("rss", "http://169.254.169.254", {})
