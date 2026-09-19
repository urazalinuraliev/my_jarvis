"""Unit tests for the watchlist chat tools (PR-B)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openexecutive.alerts.store import initialize_db as initialize_alerts_db
from openexecutive.memory.episodic import initialize_db as initialize_episodic_db
from openexecutive.monitoring import store as ms
from openexecutive.orchestrator import watchlist_tools as wt


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_watchlist_tools.db"
    monkeypatch.setattr("openexecutive.memory.episodic.DB_PATH", db_path)
    monkeypatch.setattr("openexecutive.alerts.store.DB_PATH", db_path)
    initialize_episodic_db(db_path)
    initialize_alerts_db(db_path)
    ms.initialize_db(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _passthrough_target_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise add/list/tune behavior, not feed validity, and
    predate insert-time target validation. Stub the validator to a no-op
    passthrough so an ``rss`` add doesn't make a real network call — the
    validator itself is covered by ``test_target_validation.py``."""
    async def _passthrough(
        signal_type: str, target: str, config: dict,
    ) -> tuple[str, str, dict]:
        return signal_type, target, config

    monkeypatch.setattr(wt, "validate_and_normalize_target", _passthrough)


# --------------------------------------------------------------------- #
# add_watchlist_entry
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_add_creates_row(db: Path) -> None:
    result = await wt.handle_add_watchlist_entry({
        "slug": "stock-aapl",
        "signal_type": "stock",
        "target": "AAPL",
        "display_label": "Apple",
        "trigger": {"abs_change_pct_gte": 5},
        "severity_floor": "medium",
        "route_to_specialist": "cfo",
    })
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["slug"] == "stock-aapl"
    item = ms.get_watchlist_item_by_slug("stock-aapl")
    assert item is not None
    assert item.signal_type == "stock"
    assert item.target == "AAPL"
    assert item.config_json == {"display_name": "Apple"}
    assert item.trigger_json == {"abs_change_pct_gte": 5}
    assert item.severity_floor.value == "medium"
    assert item.route_to_specialist == "cfo"


@pytest.mark.asyncio
async def test_add_rejects_unknown_signal_type(db: Path) -> None:
    result = await wt.handle_add_watchlist_entry({
        "slug": "x",
        "signal_type": "weather",  # no adapter
        "target": "https://example.com",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    assert "no registered adapter" in parsed["error"]


@pytest.mark.asyncio
async def test_add_rejects_duplicate_slug(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "stock-aapl",
        "signal_type": "stock",
        "target": "AAPL",
    })
    result = await wt.handle_add_watchlist_entry({
        "slug": "stock-aapl",
        "signal_type": "stock",
        "target": "AAPL",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    assert "already exists" in parsed["error"]


@pytest.mark.asyncio
async def test_add_rejects_unknown_mode(db: Path) -> None:
    result = await wt.handle_add_watchlist_entry({
        "slug": "x",
        "signal_type": "stock",
        "target": "AAPL",
        "mode": "forever",
    })
    parsed = json.loads(result)
    assert "error" in parsed
    assert "unknown mode" in parsed["error"]


# --------------------------------------------------------------------- #
# list_watchlist
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_filters_by_signal_type(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "s1", "signal_type": "stock", "target": "AAPL",
    })
    await wt.handle_add_watchlist_entry({
        "slug": "r1", "signal_type": "rss", "target": "https://example.com/feed",
    })

    result = json.loads(await wt.handle_list_watchlist({"signal_type": "stock"}))
    assert result["count"] == 1
    assert result["watchlist"][0]["slug"] == "s1"

    result = json.loads(await wt.handle_list_watchlist({}))
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_list_excludes_disabled_by_default(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "x", "signal_type": "stock", "target": "AAPL",
    })
    await wt.handle_tune_watchlist_entry({"slug": "x", "enabled": False})

    result = json.loads(await wt.handle_list_watchlist({}))
    assert result["count"] == 0

    result = json.loads(await wt.handle_list_watchlist({"enabled_only": False}))
    assert result["count"] == 1
    assert result["watchlist"][0]["enabled"] is False


# --------------------------------------------------------------------- #
# tune_watchlist_entry
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tune_updates_each_field(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "x", "signal_type": "stock", "target": "AAPL",
    })
    result = json.loads(await wt.handle_tune_watchlist_entry({
        "slug": "x",
        "enabled": False,
        "mode": "dry_run",
        "severity_floor": "high",
        "severity_ceiling": "urgent",
        "cadence": "hourly",
        "trigger": {"abs_change_pct_gte": 10},
        "notes": "noisy source",
    }))
    assert result["ok"] is True
    assert len(result["changes"]) == 7

    item = ms.get_watchlist_item_by_slug("x")
    assert item is not None
    assert item.enabled is False
    assert item.mode == "dry_run"
    assert item.severity_floor.value == "high"
    assert item.cadence == "hourly"
    assert item.trigger_json == {"abs_change_pct_gte": 10}
    assert item.notes == "noisy source"


@pytest.mark.asyncio
async def test_tune_requires_at_least_one_field(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "x", "signal_type": "stock", "target": "AAPL",
    })
    result = json.loads(await wt.handle_tune_watchlist_entry({"slug": "x"}))
    assert "error" in result
    assert "nothing to change" in result["error"]


@pytest.mark.asyncio
async def test_tune_rejects_unknown_slug(db: Path) -> None:
    result = json.loads(await wt.handle_tune_watchlist_entry({
        "slug": "nope", "enabled": False,
    }))
    assert "error" in result
    assert "not found" in result["error"]


# --------------------------------------------------------------------- #
# remove_watchlist_entry
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_remove_deletes_row(db: Path) -> None:
    await wt.handle_add_watchlist_entry({
        "slug": "x", "signal_type": "stock", "target": "AAPL",
    })
    result = json.loads(await wt.handle_remove_watchlist_entry({"slug": "x"}))
    assert result["ok"] is True
    assert ms.get_watchlist_item_by_slug("x") is None


@pytest.mark.asyncio
async def test_remove_rejects_unknown_slug(db: Path) -> None:
    result = json.loads(await wt.handle_remove_watchlist_entry({"slug": "nope"}))
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_add_invokes_target_validation_and_surfaces_rejection(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against the autouse passthrough hiding a removed validator call:
    override it to reject, and confirm handle_add wires it in + surfaces the
    rejection instead of inserting a dead row."""
    from openexecutive.monitoring.target_validation import WatchlistTargetError

    async def _reject(signal_type: str, target: str, config: dict) -> tuple:
        raise WatchlistTargetError("nope, not a feed")

    monkeypatch.setattr(wt, "validate_and_normalize_target", _reject)
    result = json.loads(await wt.handle_add_watchlist_entry({
        "slug": "rss-bad", "signal_type": "rss", "target": "https://x/feed",
    }))
    assert "error" in result and "not a feed" in result["error"]
    assert ms.get_watchlist_item_by_slug("rss-bad") is None
