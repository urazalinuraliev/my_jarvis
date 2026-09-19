"""Tests for the consolidate-initiatives helpers."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openexecutive.memory.episodic import (
    initialize_db,
    list_initiatives,
    store_initiative,
)
from openexecutive.memory.initiatives_consolidation import (
    Cluster,
    apply_clusters,
    propose_clusters,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "episodic.db"
    initialize_db(path)
    return path


def test_apply_clusters_merges_to_oldest_with_canonical_title(db: Path) -> None:
    store_initiative("AI Opp Assessment SKU", "active", "first summary", db_path=db)
    store_initiative("$30K AI Opp Assessment", "active", "second summary", db_path=db)
    store_initiative("AI Opp Assessment SOW", "active", "third summary", db_path=db)

    rows = list_initiatives(db_path=db)
    ids = [r.id for r in rows if r.id is not None]

    apply_clusters(
        [Cluster(canonical_title="AI Opportunity Assessment", member_ids=ids)],
        db_path=db,
    )

    remaining = list_initiatives(db_path=db)
    assert len(remaining) == 1
    assert remaining[0].title == "AI Opportunity Assessment"
    # Most-recent non-empty summary wins ("third summary" — last inserted bumps updated_at).
    assert remaining[0].summary == "third summary"


def test_apply_clusters_skips_singletons(db: Path) -> None:
    store_initiative("Alone", "active", "x", db_path=db)
    [row] = list_initiatives(db_path=db)
    assert row.id is not None

    result = apply_clusters([Cluster(canonical_title="Alone", member_ids=[row.id])], db_path=db)
    assert result == {"clusters_merged": 0, "rows_deleted": 0}
    assert len(list_initiatives(db_path=db)) == 1


def _fake_provider(tool_input: dict) -> SimpleNamespace:
    tool_block = SimpleNamespace(type="tool_use", name="propose_clusters", input=tool_input)
    return SimpleNamespace(messages_create=AsyncMock(return_value=SimpleNamespace(content=[tool_block])))


@pytest.mark.asyncio
async def test_propose_clusters_drops_overlapping_member_ids(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the model emits two clusters that share a member_id, the second
    must not claim already-assigned ids — otherwise the survivor of cluster A
    could be re-renamed or deleted by cluster B."""
    for n in range(4):
        store_initiative(f"row {n}", "active", f"s{n}", db_path=db)
    ids = [r.id for r in list_initiatives(db_path=db) if r.id is not None]
    assert len(ids) == 4

    # Cluster A claims ids[0..2]; cluster B tries to also claim ids[2] alongside ids[3] —
    # only ids[3] is unclaimed, so cluster B should collapse to a singleton and be dropped.
    tool_input = {
        "clusters": [
            {"canonical_title": "First merge", "member_ids": ids[0:3]},
            {"canonical_title": "Greedy second", "member_ids": [ids[2], ids[3]]},
        ]
    }
    provider = _fake_provider(tool_input)
    monkeypatch.setattr("openexecutive.providers.get_provider", lambda _m: provider)
    monkeypatch.setattr(
        "openexecutive.config.get_settings",
        lambda: SimpleNamespace(routing_model="claude-test"),
    )

    _, clusters = await propose_clusters(db_path=db)
    assert len(clusters) == 1
    assert clusters[0].canonical_title == "First merge"


@pytest.mark.asyncio
async def test_propose_clusters_tolerates_bad_member_ids(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-numeric, None, bool, or unknown ids must be skipped without crashing."""
    for n in range(3):
        store_initiative(f"r{n}", "active", "s", db_path=db)
    ids = [r.id for r in list_initiatives(db_path=db) if r.id is not None]

    tool_input = {
        "clusters": [
            {
                "canonical_title": "Cleaned",
                "member_ids": [ids[0], "not-a-number", None, True, 999_999, ids[1]],
            }
        ]
    }
    provider = _fake_provider(tool_input)
    monkeypatch.setattr("openexecutive.providers.get_provider", lambda _m: provider)
    monkeypatch.setattr(
        "openexecutive.config.get_settings",
        lambda: SimpleNamespace(routing_model="claude-test"),
    )

    _, clusters = await propose_clusters(db_path=db)
    assert len(clusters) == 1
    assert set(clusters[0].member_ids) == {ids[0], ids[1]}


@pytest.mark.asyncio
async def test_propose_clusters_returns_empty_for_singleton_db(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With < 2 active initiatives there's nothing to cluster — never call the LLM."""
    store_initiative("only one", "active", "x", db_path=db)
    create_mock = AsyncMock()
    monkeypatch.setattr(
        "openexecutive.providers.get_provider",
        lambda _m: SimpleNamespace(messages_create=create_mock),
    )
    monkeypatch.setattr(
        "openexecutive.config.get_settings",
        lambda: SimpleNamespace(routing_model="claude-test"),
    )

    initiatives, clusters = await propose_clusters(db_path=db)
    assert len(initiatives) == 1
    assert clusters == []
    create_mock.assert_not_called()
