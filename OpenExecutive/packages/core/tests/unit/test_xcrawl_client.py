"""Unit tests for the xcrawl REST client.

Covers the gate (disabled / no-key → empty), the nested-envelope parser,
and graceful degradation on transport failure. No network: ``httpx`` is
monkeypatched with a fake client.
"""
from __future__ import annotations

from typing import Any

import pytest

from openexecutive.integrations import xcrawl_client


class _FakeResponse:
    def __init__(self, body: Any, *, raise_exc: Exception | None = None) -> None:
        self._body = body
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self) -> Any:
        return self._body


class _FakeClient:
    """Stand-in for httpx.AsyncClient. Configure class attrs per test."""

    body: Any = {}
    raise_on_post: Exception | None = None
    raise_on_status: Exception | None = None
    last_call: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def post(
        self, url: str, *, headers: Any = None, json: Any = None,
    ) -> _FakeResponse:
        _FakeClient.last_call = {"url": url, "headers": headers, "json": json}
        if _FakeClient.raise_on_post is not None:
            raise _FakeClient.raise_on_post
        return _FakeResponse(_FakeClient.body, raise_exc=_FakeClient.raise_on_status)


_NESTED_BODY = {
    "status": "completed",
    "total_credits_used": 2,
    "data": {
        "data": [
            {"position": 1, "title": "USTR finalizes tariffs",
             "description": "Section 301 increases", "url": "https://a.example/1"},
            {"position": 2, "title": "BYD news",
             "description": "EV exports", "url": "https://b.example/2"},
            {"position": 3, "title": "no url row", "description": "skip me"},
        ]
    },
}


@pytest.fixture
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    monkeypatch.setenv("XCRAWL_API_KEY", "test-key")
    _FakeClient.body = {}
    _FakeClient.raise_on_post = None
    _FakeClient.raise_on_status = None
    _FakeClient.last_call = {}
    monkeypatch.setattr(xcrawl_client.httpx, "AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_search_disabled_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "false")
    monkeypatch.setenv("XCRAWL_API_KEY", "test-key")
    assert await xcrawl_client.search("anything") == []


@pytest.mark.asyncio
async def test_search_enabled_without_key_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    # Empty env value overrides any key supplied by the repo's .env file —
    # otherwise get_settings() reads the real key and this would make a
    # live call. Empty key trips the disabled gate before any HTTP.
    monkeypatch.setenv("XCRAWL_API_KEY", "")
    assert await xcrawl_client.search("anything") == []


@pytest.mark.asyncio
async def test_search_blank_query_returns_empty(_enabled: None) -> None:
    assert await xcrawl_client.search("   ") == []


@pytest.mark.asyncio
async def test_search_parses_nested_envelope(_enabled: None) -> None:
    _FakeClient.body = _NESTED_BODY
    results = await xcrawl_client.search("ev tariffs", limit=5)
    # The third row has no URL and must be dropped.
    assert [r.url for r in results] == [
        "https://a.example/1", "https://b.example/2",
    ]
    assert results[0].title == "USTR finalizes tariffs"
    assert results[0].snippet == "Section 301 increases"
    # Endpoint + auth header wired correctly.
    assert _FakeClient.last_call["url"].endswith("/search")
    assert _FakeClient.last_call["headers"]["Authorization"] == "Bearer test-key"
    assert _FakeClient.last_call["json"]["query"] == "ev tariffs"


@pytest.mark.asyncio
async def test_search_respects_limit(_enabled: None) -> None:
    _FakeClient.body = _NESTED_BODY
    results = await xcrawl_client.search("ev tariffs", limit=1)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_transport_failure_returns_empty(_enabled: None) -> None:
    _FakeClient.raise_on_post = RuntimeError("connection reset")
    assert await xcrawl_client.search("ev tariffs") == []


@pytest.mark.asyncio
async def test_search_http_status_error_returns_empty(_enabled: None) -> None:
    # raise_for_status() raising (e.g. 401) is handled inside the client
    # context and degrades to [].
    _FakeClient.raise_on_status = RuntimeError("HTTP 401 Unauthorized")
    assert await xcrawl_client.search("ev tariffs") == []


@pytest.mark.asyncio
async def test_search_limit_zero_returns_empty(_enabled: None) -> None:
    # limit<=0 must NOT silently return a charged-but-dropped result.
    _FakeClient.body = _NESTED_BODY
    assert await xcrawl_client.search("ev tariffs", limit=0) == []


@pytest.mark.asyncio
async def test_scrape_disabled_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "false")
    monkeypatch.setenv("XCRAWL_API_KEY", "test-key")
    assert await xcrawl_client.scrape("https://x.example") is None


@pytest.mark.asyncio
async def test_scrape_blank_url_returns_none(_enabled: None) -> None:
    assert await xcrawl_client.scrape("  ") is None


@pytest.mark.asyncio
async def test_scrape_returns_markdown(_enabled: None) -> None:
    _FakeClient.body = {"status": "completed", "total_credits_used": 1,
                        "data": {"markdown": "# Title\n\nbody text",
                                 "metadata": {"status_code": 200}}}
    md = await xcrawl_client.scrape("https://x.example/page")
    assert md == "# Title\n\nbody text"
    assert _FakeClient.last_call["url"].endswith("/scrape")
    assert _FakeClient.last_call["json"]["url"] == "https://x.example/page"
    assert _FakeClient.last_call["json"]["output"]["formats"] == ["markdown"]


@pytest.mark.asyncio
async def test_scrape_blank_markdown_is_none(_enabled: None) -> None:
    _FakeClient.body = {"data": {"markdown": "   \n  "}}
    assert await xcrawl_client.scrape("https://x.example") is None


@pytest.mark.asyncio
async def test_scrape_transport_failure_returns_none(_enabled: None) -> None:
    _FakeClient.raise_on_post = RuntimeError("timeout")
    assert await xcrawl_client.scrape("https://x.example") is None


# --------------------------------------------------------------------- #
# scrape_detailed — status distinguishes infra failure from empty page
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_scrape_detailed_ok(_enabled: None) -> None:
    _FakeClient.body = {"data": {"markdown": "# Title\n\nbody"}}
    out = await xcrawl_client.scrape_detailed("https://x.example/page")
    assert out == xcrawl_client.ScrapeOutcome("# Title\n\nbody", "ok")


@pytest.mark.asyncio
async def test_scrape_detailed_empty_page(_enabled: None) -> None:
    # Fetched OK (200) but no usable markdown → 'empty', not 'error'.
    _FakeClient.body = {"data": {"markdown": "   \n  "}}
    out = await xcrawl_client.scrape_detailed("https://x.example")
    assert out.markdown is None
    assert out.status == "empty"


@pytest.mark.asyncio
async def test_scrape_detailed_transport_error(_enabled: None) -> None:
    _FakeClient.raise_on_post = RuntimeError("connection reset")
    out = await xcrawl_client.scrape_detailed("https://x.example")
    assert out.markdown is None
    assert out.status == "error"


@pytest.mark.asyncio
async def test_scrape_detailed_http_status_error(_enabled: None) -> None:
    # raise_for_status() raising (401/429) is an infra error, not an empty page.
    _FakeClient.raise_on_status = RuntimeError("HTTP 429 Too Many Requests")
    out = await xcrawl_client.scrape_detailed("https://x.example")
    assert out.status == "error"


@pytest.mark.asyncio
async def test_scrape_detailed_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "false")
    monkeypatch.setenv("XCRAWL_API_KEY", "test-key")
    out = await xcrawl_client.scrape_detailed("https://x.example")
    assert out == xcrawl_client.ScrapeOutcome(None, "disabled")


@pytest.mark.asyncio
async def test_scrape_detailed_blank_url_disabled(_enabled: None) -> None:
    out = await xcrawl_client.scrape_detailed("  ")
    assert out.status == "disabled"


def test_parse_scrape_shapes() -> None:
    assert xcrawl_client._parse_scrape({"data": {"markdown": "x"}}) == "x"
    assert xcrawl_client._parse_scrape({"data": {"data": {"markdown": "y"}}}) == "y"
    assert xcrawl_client._parse_scrape({}) is None
    assert xcrawl_client._parse_scrape({"data": None}) is None
    assert xcrawl_client._parse_scrape({"data": {"markdown": ""}}) is None


def test_parse_search_tolerates_flat_list() -> None:
    body = {"data": [{"title": "t", "url": "https://x.example", "description": "d"}]}
    results = xcrawl_client._parse_search(body)
    assert len(results) == 1 and results[0].url == "https://x.example"


def test_parse_search_handles_garbage() -> None:
    assert xcrawl_client._parse_search({}) == []
    assert xcrawl_client._parse_search({"data": None}) == []
    assert xcrawl_client._parse_search({"data": {"data": "nope"}}) == []
