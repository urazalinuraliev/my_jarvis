"""Tests for the dedicated watchlist-analysis pass + research-artifact
persistence in the executive_research workflow.

The provider is stubbed at the boundary (no API calls). The watchlist
handler runs for real against a temp episodic DB so we exercise the
actual insert + slug-dedup safety net.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from openexecutive.alerts.store import initialize_db as initialize_alerts_db
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.memory.episodic import initialize_db as initialize_episodic_db
from openexecutive.monitoring import store as monitoring_store
from openexecutive.monitoring.research.models import ResearchFinding
from openexecutive.workflows import executive_research as er


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_research.db"
    monkeypatch.setattr("openexecutive.memory.episodic.DB_PATH", db_path)
    monkeypatch.setattr("openexecutive.alerts.store.DB_PATH", db_path)
    initialize_episodic_db(db_path)
    initialize_alerts_db(db_path)
    monitoring_store.initialize_db(db_path)
    return db_path


def _finding(title: str = "Tesla cut prices") -> ResearchFinding:
    return ResearchFinding(
        title=title,
        summary="Detail with a source.",
        severity_hint="high",
        suggested_audience="principal",
        confidence="high",
        relevant_urls=["https://example.com/feed.xml"],
    )


def _resp(tool_uses: list[tuple[str, dict[str, Any]]], stop_reason: str = "end_turn"):
    msg = MagicMock()
    msg.stop_reason = stop_reason
    blocks = []
    for idx, (name, inp) in enumerate(tool_uses):
        b = MagicMock()
        b.type = "tool_use"
        b.id = f"tu{idx}"
        b.name = name
        b.input = inp
        blocks.append(b)
    msg.content = blocks
    return msg


def _stub_provider(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> None:
    state = {"i": 0}

    class FakeProvider:
        async def messages_create(self, **kwargs):
            r = responses[min(state["i"], len(responses) - 1)]
            state["i"] += 1
            return r

    monkeypatch.setattr(
        "openexecutive.providers.get_provider", lambda model: FakeProvider()
    )


class FakeStore:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict[str, Any]]] = {}

    def add_documents(self, texts, metadatas, ids, collection):
        col = self.collections.setdefault(collection, [])
        for t, m, i in zip(texts, metadatas, ids, strict=False):
            col[:] = [r for r in col if r["id"] != i]
            col.append({"id": i, "text": t, "metadata": m})

    def delete_documents(self, collection, where):
        col = self.collections.get(collection, [])
        self.collections[collection] = [
            r
            for r in col
            if not all(r["metadata"].get(k) == v for k, v in where.items())
        ]

    def query(self, query_text, collection, domain_filter=None, n_results=5):
        return []


@pytest.mark.asyncio
async def test_watchlist_pass_adds_entry(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_provider(monkeypatch, [
        _resp([("add_watchlist_entry", {
            "slug": "stock-tsla", "signal_type": "stock", "target": "TSLA",
        })]),
    ])
    calls = await er._watchlist_analysis_loop([_finding()], existing_watchlist=[])
    assert any(c["tool"] == "add_watchlist_entry" and c["ok"] for c in calls)
    slugs = [w.slug for w in monitoring_store.list_watchlist(db_path=db)]
    assert "stock-tsla" in slugs


@pytest.mark.asyncio
async def test_watchlist_pass_respects_budget(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # One response asking for more adds than the budget allows.
    over = [
        ("add_watchlist_entry", {
            "slug": f"stock-x{i}", "signal_type": "stock", "target": f"X{i}",
        })
        for i in range(er._MAX_WATCHLIST_ADDS_PER_RUN + 3)
    ]
    _stub_provider(monkeypatch, [_resp(over, stop_reason="tool_use")])
    calls = await er._watchlist_analysis_loop([_finding()], existing_watchlist=[])
    ok = [c for c in calls if c["ok"]]
    assert len(ok) == er._MAX_WATCHLIST_ADDS_PER_RUN
    assert len(monitoring_store.list_watchlist(db_path=db)) == er._MAX_WATCHLIST_ADDS_PER_RUN


@pytest.mark.asyncio
async def test_watchlist_pass_skips_already_watched(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-existing entry; the handler's slug-dedup is the safety net even if
    # the model re-proposes it.
    monitoring_store.insert_watchlist_item(
        slug="stock-tsla", signal_type="stock", target="TSLA", db_path=db,
    )
    _stub_provider(monkeypatch, [
        _resp([("add_watchlist_entry", {
            "slug": "stock-tsla", "signal_type": "stock", "target": "TSLA",
        })]),
    ])
    calls = await er._watchlist_analysis_loop([_finding()], existing_watchlist=[])
    assert all(not c["ok"] for c in calls)  # rejected: slug already exists
    assert len(monitoring_store.list_watchlist(db_path=db)) == 1


@pytest.mark.asyncio
async def test_watchlist_pass_empty_findings_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # No provider call should happen for empty findings.
    monkeypatch.setattr(
        "openexecutive.providers.get_provider",
        lambda model: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert await er._watchlist_analysis_loop([], existing_watchlist=[]) == []


@pytest.mark.asyncio
async def test_run_persists_artifact_as_recent_research(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_research_one(slug, agent, ctx):
        return [_finding()] if slug == "cso" else []

    async def fake_synth(deduped):
        return ("ran", [])

    async def fake_watchlist(findings, existing_watchlist):
        return []

    monkeypatch.setattr(er, "research_one_specialist", fake_research_one)
    monkeypatch.setattr(er, "_executive_synthesis_loop", fake_synth)
    monkeypatch.setattr(er, "_watchlist_analysis_loop", fake_watchlist)

    store = FakeStore()
    # Seed a STALE prior-run research doc under a different source_name/id so
    # the keep-latest delete-by-metadata path is what must remove it (not an
    # id-upsert collision).
    store.add_documents(
        ["stale prior research from another day"],
        [{"type": "recent_research", "filename": "recent_research_2000-01-01"}],
        ["stale-1"],
        ChromaDBStore.RESEARCH_COLLECTION,
    )
    workflow = er.ExecutiveResearchWorkflow()

    async def _drive():
        async for _ in workflow.run(inputs=er.ExecutiveResearchInput(), store=store):
            pass

    await _drive()
    rows = store.collections.get(ChromaDBStore.RESEARCH_COLLECTION, [])
    assert rows, "artifact not persisted to recent_research"
    assert all(r["metadata"]["type"] == "recent_research" for r in rows)
    # keep-latest: the differently-named stale doc must be gone (proves the
    # delete-by-metadata clear ran, independent of id-upsert).
    assert all("stale prior research" not in r["text"] for r in rows)
    first_count = len(rows)

    # Second run: keep-latest — count must not double.
    await _drive()
    rows2 = store.collections.get(ChromaDBStore.RESEARCH_COLLECTION, [])
    assert len(rows2) == first_count


@pytest.mark.asyncio
async def test_watchlist_pass_multi_iteration(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the message-threading path: iter 1 adds with stop_reason
    'tool_use' (budget remaining) so the loop continues; iter 2 ends."""
    r1 = _resp(
        [("add_watchlist_entry", {
            "slug": "stock-tsla", "signal_type": "stock", "target": "TSLA",
        })],
        stop_reason="tool_use",
    )
    r2 = _resp([], stop_reason="end_turn")
    _stub_provider(monkeypatch, [r1, r2])
    calls = await er._watchlist_analysis_loop([_finding()], existing_watchlist=[])
    ok = [c for c in calls if c["ok"]]
    assert len(ok) == 1
    assert "stock-tsla" in [w.slug for w in monitoring_store.list_watchlist(db_path=db)]


def test_render_artifact_splits_watchlist_and_shows_failures() -> None:
    """add_watchlist_entry calls move out of 'Actions routed' into 'Now
    watching', and failed adds (e.g. slug-dedup) are still shown (with ✗)."""
    tool_calls = [
        {"tool": "send_discord_dm", "result_preview": "{'status': 'sent'}", "ok": True},
        {
            "tool": "add_watchlist_entry",
            "result_preview": "{'ok': true, 'slug': 'stock-tsla'}",
            "ok": True,
        },
        {
            "tool": "add_watchlist_entry",
            "result_preview": "{'error': 'slug already exists'}",
            "ok": False,
        },
    ]
    art = er._render_artifact(
        deduped=[], per_specialist=[], tool_calls=tool_calls,
        narrative="n", note="",
    )
    assert "## Now watching" in art
    assert "stock-tsla" in art
    assert "slug already exists" in art  # failed add still surfaced
    routed_section = art.split("## Now watching")[0]
    assert "add_watchlist_entry" not in routed_section  # moved out of routed
    assert "send_discord_dm" in routed_section  # DM stays under Actions routed
