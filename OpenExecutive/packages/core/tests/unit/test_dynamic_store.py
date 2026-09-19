"""CRUD round-trip tests for the dynamic-workflow definition store."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from openexecutive.workflows import dynamic_store  # noqa: E402
from openexecutive.workflows.dynamic_models import DynamicWorkflowDef  # noqa: E402


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "episodic.db"
    dynamic_store.initialize_dynamic_workflows_db(path)
    return path


def _def(name: str = "weekly_watch", **overrides) -> DynamicWorkflowDef:
    base = {
        "name": name,
        "title": "Weekly Watch",
        "steps": [
            {"kind": "specialist", "id": "research", "title": "Research", "specialist": "cso", "goal": "Go."},
            {"kind": "synthesis", "id": "assemble", "title": "Assemble"},
        ],
    }
    base.update(overrides)
    return DynamicWorkflowDef.model_validate(base)


def test_upsert_and_get(db: Path) -> None:
    dynamic_store.upsert_definition(_def(), db_path=db)
    got = dynamic_store.get_definition("weekly_watch", db_path=db)
    assert got is not None
    assert got.title == "Weekly Watch"
    assert got.created_at and got.updated_at


def test_get_missing_returns_none(db: Path) -> None:
    assert dynamic_store.get_definition("nope", db_path=db) is None


def test_list_active_only(db: Path) -> None:
    dynamic_store.upsert_definition(_def("active_wf"), db_path=db)
    dynamic_store.upsert_definition(_def("inactive_wf", is_active=False), db_path=db)
    active = [d.name for d in dynamic_store.list_definitions(active_only=True, db_path=db)]
    everything = [d.name for d in dynamic_store.list_definitions(active_only=False, db_path=db)]
    assert active == ["active_wf"]
    assert set(everything) == {"active_wf", "inactive_wf"}


def test_update_preserves_created_at(db: Path) -> None:
    first = dynamic_store.upsert_definition(_def(), db_path=db)
    updated = dynamic_store.upsert_definition(
        _def(title="Renamed"), db_path=db
    )
    assert updated.created_at == first.created_at
    assert updated.title == "Renamed"


def test_set_active_toggles(db: Path) -> None:
    dynamic_store.upsert_definition(_def(), db_path=db)
    assert dynamic_store.set_active("weekly_watch", False, db_path=db) is True
    got = dynamic_store.get_definition("weekly_watch", db_path=db)
    assert got is not None and got.is_active is False
    # active_only list now excludes it.
    assert dynamic_store.list_definitions(active_only=True, db_path=db) == []


def test_set_active_missing_returns_false(db: Path) -> None:
    assert dynamic_store.set_active("nope", True, db_path=db) is False


def test_delete(db: Path) -> None:
    dynamic_store.upsert_definition(_def(), db_path=db)
    assert dynamic_store.delete_definition("weekly_watch", db_path=db) is True
    assert dynamic_store.delete_definition("weekly_watch", db_path=db) is False
    assert dynamic_store.get_definition("weekly_watch", db_path=db) is None


def test_missing_db_is_safe(tmp_path: Path) -> None:
    missing = tmp_path / "absent.db"
    assert dynamic_store.list_definitions(db_path=missing) == []
    assert dynamic_store.get_definition("x", db_path=missing) is None
    assert dynamic_store.delete_definition("x", db_path=missing) is False
