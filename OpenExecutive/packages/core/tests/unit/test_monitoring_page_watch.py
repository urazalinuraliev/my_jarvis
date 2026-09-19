"""Unit tests for the page_watch change-detection adapter (P2)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openexecutive.alerts.models import AlertSeverity
from openexecutive.alerts.store import initialize_db as initialize_alerts_db
from openexecutive.memory.episodic import initialize_db as initialize_episodic_db
from openexecutive.monitoring import store as ms
from openexecutive.monitoring.models import WatchlistItem
from openexecutive.monitoring.sources import list_registered_kinds
from openexecutive.monitoring.sources.page_watch import (
    PageWatchSource,
    _diff,
    _html_to_text,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_page_watch.db"
    monkeypatch.setattr("openexecutive.memory.episodic.DB_PATH", db_path)
    monkeypatch.setattr("openexecutive.alerts.store.DB_PATH", db_path)
    initialize_episodic_db(db_path)
    initialize_alerts_db(db_path)
    ms.initialize_db(db_path)
    return db_path


def _make_item(
    *, slug: str = "page-acme", target: str = "https://acme.example/pricing",
    config: dict | None = None, trigger: dict | None = None,
) -> WatchlistItem:
    return WatchlistItem(
        id=1, slug=slug, signal_type="page_watch", target=target,
        config_json=config or {}, trigger_json=trigger or {},
    )


class _Page:
    """Mutable body holder so a test can change the 'served' page between polls."""

    def __init__(self, body: bytes) -> None:
        self.body = body


def _install(monkeypatch: pytest.MonkeyPatch, page: _Page) -> None:
    async def fake_fetch(url: str, max_bytes: int, **kwargs: object) -> bytes:
        return page.body

    monkeypatch.setattr("openexecutive.monitoring.sources.page_watch.fetch_bounded", fake_fetch)
    monkeypatch.setattr(
        "openexecutive.monitoring.sources.page_watch.validate_target_url",
        lambda u: (True, ""),
    )


# --------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------- #


def test_html_to_text_strips_markup_and_scripts() -> None:
    body = b"""
    <html><head><style>.x{color:red}</style>
    <script>var a = 1 < 2;</script></head>
    <body><!-- comment --><h1>Pricing</h1>
    <p>Pro&nbsp;plan is &pound;30/mo</p></body></html>
    """
    text = _html_to_text(body)
    assert "Pricing" in text
    assert "£30/mo" in text  # &nbsp; and &pound; entities unescaped
    # script/style content must not survive
    assert "color:red" not in text
    assert "var a" not in text
    # collapsed whitespace (no double spaces)
    assert "  " not in text


def test_diff_reports_percent_and_added_text() -> None:
    pct, added = _diff("the price is ten", "the price is twenty now")
    assert "twenty" in added
    assert 0 < pct <= 100


# --------------------------------------------------------------------- #
# poll() lifecycle
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_poll_baselines_without_alert(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(b"<html><body><h1>Pro plan $30/mo</h1></body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()

    signals = await src.poll(item, db_path=db)
    assert signals == []  # baseline, no alert

    state = ms.get_page_watch_state("page-acme", db_path=db)
    assert state is not None
    assert state["content_hash"]


@pytest.mark.asyncio
async def test_unchanged_poll_emits_nothing(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(b"<html><body>same content</body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()
    await src.poll(item, db_path=db)        # baseline
    assert await src.poll(item, db_path=db) == []  # unchanged


@pytest.mark.asyncio
async def test_changed_poll_emits_signal_and_updates_state(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(b"<html><body><h1>Pro plan $30/mo</h1></body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item(config={"label": "Acme pricing"})

    await src.poll(item, db_path=db)  # baseline
    state1 = ms.get_page_watch_state("page-acme", db_path=db)

    # Price change.
    page.body = b"<html><body><h1>Pro plan $45/mo</h1></body></html>"
    signals = await src.poll(item, db_path=db)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.severity_hint == AlertSeverity.LOW
    assert sig.provenance_url == "https://acme.example/pricing"
    assert sig.normalized_summary.startswith("[Acme pricing] page changed —")
    assert "45" in sig.raw_payload["added_text"]
    assert sig.dedup_key.startswith("page_watch:")

    # State advanced to the new hash.
    state2 = ms.get_page_watch_state("page-acme", db_path=db)
    assert state2["content_hash"] != state1["content_hash"]

    # Re-polling the now-current page is quiet again.
    assert await src.poll(item, db_path=db) == []


@pytest.mark.asyncio
async def test_change_beyond_snapshot_cap_is_still_detected(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection hashes the FULL text, so a change past the snapshot cap fires."""
    filler = "word " * 60_000  # ~300k chars of normalized text, > _MAX_TEXT_CHARS
    page = _Page(f"<body>{filler}END_A</body>".encode())
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()
    await src.poll(item, db_path=db)  # baseline

    # The only change is at the very end, well beyond the 100k snapshot cap.
    page.body = f"<body>{filler}END_B</body>".encode()
    signals = await src.poll(item, db_path=db)
    assert len(signals) == 1  # full-text hash caught it


@pytest.mark.asyncio
async def test_markup_only_change_does_not_alert(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(b"<html><body><h1>Hello</h1></body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()
    await src.poll(item, db_path=db)  # baseline

    # Same visible text, different markup / whitespace / attributes.
    page.body = b"<html>\n  <body>\n    <h1 class='t'>Hello</h1>\n  </body>\n</html>"
    assert await src.poll(item, db_path=db) == []


@pytest.mark.asyncio
async def test_keyword_trigger_matches_changed_text_only(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keyword filter matches the CHANGE (added text), not the whole page."""
    page = _Page(b"<html><body>Plans: Pro and Team</body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()
    await src.poll(item, db_path=db)  # baseline

    # New text introduces an Enterprise tier.
    page.body = b"<html><body>Plans: Pro and Team and Enterprise</body></html>"
    signals = await src.poll(item, db_path=db)
    assert len(signals) == 1
    assert "Enterprise" in signals[0].raw_payload["added_text"]

    # A keyword in the added text → kept.
    assert src.matches_trigger(
        signals[0], _make_item(trigger={"keywords": ["enterprise"]})
    )
    # A keyword absent from the change → filtered out (even if elsewhere on page).
    assert not src.matches_trigger(
        signals[0], _make_item(trigger={"keywords": ["acquisition"]})
    )
    # No keywords → permissive.
    assert src.matches_trigger(signals[0], _make_item())


@pytest.mark.asyncio
async def test_empty_extraction_skips(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _Page(b"<html><head><script>noop()</script></head><body></body></html>")
    _install(monkeypatch, page)
    src = PageWatchSource()
    item = _make_item()
    assert await src.poll(item, db_path=db) == []
    # No baseline stored for an empty page.
    assert ms.get_page_watch_state("page-acme", db_path=db) is None


@pytest.mark.asyncio
async def test_bad_target_and_fetch_failure_return_empty(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    src = PageWatchSource()
    # Empty target.
    assert await src.poll(_make_item(target=""), db_path=db) == []

    # Fetch failure.
    async def boom(url: str, max_bytes: int, **kwargs: object) -> bytes:
        raise httpx.ConnectError("dns")

    monkeypatch.setattr("openexecutive.monitoring.sources.page_watch.fetch_bounded", boom)
    monkeypatch.setattr(
        "openexecutive.monitoring.sources.page_watch.validate_target_url",
        lambda u: (True, ""),
    )
    assert await src.poll(_make_item(), db_path=db) == []


# --------------------------------------------------------------------- #
# store + registration
# --------------------------------------------------------------------- #


def test_page_watch_state_roundtrip(db: Path) -> None:
    assert ms.get_page_watch_state("s1", db_path=db) is None
    ms.upsert_page_watch_state("s1", "hashA", "text A", db_path=db)
    st = ms.get_page_watch_state("s1", db_path=db)
    assert st is not None and st["content_hash"] == "hashA"
    # Upsert replaces.
    ms.upsert_page_watch_state("s1", "hashB", "text B", db_path=db)
    st2 = ms.get_page_watch_state("s1", db_path=db)
    assert st2["content_hash"] == "hashB"
    assert st2["text_snapshot"] == "text B"


def test_page_watch_registered() -> None:
    assert "page_watch" in list_registered_kinds()


# --------------------------------------------------------------------- #
# xcrawl fetch path (config_json["fetch"] == "xcrawl")
# --------------------------------------------------------------------- #


def _install_xcrawl(monkeypatch: pytest.MonkeyPatch, holder: SimpleNamespace) -> None:
    """Patch validate + xcrawl_client.scrape; leave fetch_bounded alone so a
    test fails loudly if the xcrawl row wrongly falls back to httpx."""
    async def fake_scrape(url: str) -> str | None:
        holder.calls += 1
        return holder.md

    async def boom_fetch(url: str, max_bytes: int, **kwargs: object) -> bytes:
        raise AssertionError("xcrawl row must NOT fall back to httpx fetch_bounded")

    monkeypatch.setattr(
        "openexecutive.monitoring.sources.page_watch.validate_target_url",
        lambda u: (True, ""),
    )
    # Make any httpx fallback blow up so the test proves the xcrawl route.
    monkeypatch.setattr(
        "openexecutive.monitoring.sources.page_watch.fetch_bounded", boom_fetch,
    )
    monkeypatch.setattr(
        "openexecutive.integrations.xcrawl_client.scrape", fake_scrape,
    )


@pytest.mark.asyncio
async def test_page_watch_xcrawl_detects_change(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = SimpleNamespace(md="# Pricing\n\nPro plan is $30/mo", calls=0)
    _install_xcrawl(monkeypatch, holder)
    item = _make_item(slug="page-xc", config={"fetch": "xcrawl"})
    src = PageWatchSource()

    assert await src.poll(item, db_path=db) == []          # baseline
    assert await src.poll(item, db_path=db) == []          # unchanged
    holder.md = "# Pricing\n\nPro plan is $40/mo"
    signals = await src.poll(item, db_path=db)             # changed
    assert len(signals) == 1
    assert signals[0].source_kind == "page_watch"
    assert "$40/mo" in signals[0].raw_payload["added_text"]
    assert holder.calls == 3  # every poll went through xcrawl, not httpx


@pytest.mark.asyncio
async def test_page_watch_xcrawl_failure_drops_tick(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = SimpleNamespace(md=None, calls=0)  # scrape returns nothing
    _install_xcrawl(monkeypatch, holder)
    item = _make_item(slug="page-xc2", config={"fetch": "xcrawl"})
    assert await PageWatchSource().poll(item, db_path=db) == []
    # No baseline stored, so a later successful scrape is treated as first-seen.
    assert ms.get_page_watch_state("page-xc2", db_path=db) is None


@pytest.mark.asyncio
async def test_page_watch_xcrawl_whitespace_only_drops_without_baseline(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Markdown that normalizes to empty (e.g. truncated to a whitespace prefix)
    # must be treated as "no fetch", not an empty baseline.
    holder = SimpleNamespace(md="   \n\t  ", calls=0)
    _install_xcrawl(monkeypatch, holder)
    item = _make_item(slug="page-xc3", config={"fetch": "xcrawl"})
    assert await PageWatchSource().poll(item, db_path=db) == []
    assert ms.get_page_watch_state("page-xc3", db_path=db) is None
