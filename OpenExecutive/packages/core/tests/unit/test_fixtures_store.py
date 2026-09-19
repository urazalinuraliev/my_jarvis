"""Store-level tests for user-generated fixtures."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openexecutive.fixtures import store as fx_store


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "episodic.db"
    monkeypatch.setattr(fx_store, "DB_PATH", path)
    fx_store.initialize_db(path)
    return path


def _insert(name: str = "acme", **over: object) -> int:
    kwargs: dict[str, object] = dict(
        name=name,
        display_name="Acme Inc",
        scenario_description="a test company",
        profile_yaml="company:\n  name: Acme Inc\n",
        people_yaml="people: []\n",
        departments_yaml="departments: []\n",
        memory_json="{}",
        docs_json="{}",
        industry="Widgets",
        stage="Seed",
        arr=1000000.0,
        headcount=10,
        founding_year=2020,
        mission="make widgets",
        doc_count=3,
    )
    kwargs.update(over)
    return fx_store.insert_fixture(**kwargs)  # type: ignore[arg-type]


def test_initialize_idempotent(db: Path) -> None:
    fx_store.initialize_db(db)
    fx_store.initialize_db(db)
    assert fx_store.list_fixtures(db) == []


def test_insert_and_get(db: Path) -> None:
    rid = _insert()
    assert rid > 0
    row = fx_store.get_fixture("acme", db)
    assert row is not None
    assert row["display_name"] == "Acme Inc"
    assert row["profile_yaml"].startswith("company:")


def test_list_tags_source_and_summary(db: Path) -> None:
    _insert(
        dept_summary_json='[{"title": "Finance", "head": "Sam"}]',
        people_summary_json='[{"name": "Sam", "role": "CFO", "is_principal": true}]',
    )
    rows = fx_store.list_fixtures(db)
    assert len(rows) == 1
    assert rows[0]["source"] == "generated"
    assert rows[0]["industry"] == "Widgets"
    assert rows[0]["doc_count"] == 3
    # Org summaries are parsed back into the curated list shape for the cards.
    assert rows[0]["departments"] == [{"title": "Finance", "head": "Sam"}]
    assert rows[0]["people"] == [{"name": "Sam", "role": "CFO", "is_principal": True}]
    # The serialized artifact + raw JSON columns are NOT in the list summary.
    assert "profile_yaml" not in rows[0]
    assert "dept_summary_json" not in rows[0]


def test_name_exists(db: Path) -> None:
    assert fx_store.fixture_name_exists("acme", db) is False
    _insert()
    assert fx_store.fixture_name_exists("acme", db) is True


def test_unique_name_collision_raises(db: Path) -> None:
    _insert()
    with pytest.raises(sqlite3.IntegrityError):
        _insert()


def test_soft_delete(db: Path) -> None:
    _insert()
    assert fx_store.delete_fixture("acme", db) is True
    assert fx_store.get_fixture("acme", db) is None
    assert fx_store.list_fixtures(db) == []
    # The name STILL occupies the UNIQUE slot — so slug derivation routes around
    # it instead of colliding on re-create (regression guard for the delete →
    # recreate-same-name 409 dead-end).
    assert fx_store.fixture_name_exists("acme", db) is True
    # Deleting again is a no-op.
    assert fx_store.delete_fixture("acme", db) is False


def test_archived_name_still_collides_on_insert(db: Path) -> None:
    _insert()
    fx_store.delete_fixture("acme", db)
    # Re-using a soft-deleted name must raise (UNIQUE is over all rows), which
    # is exactly why fixture_name_exists reports archived names as taken.
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db_path=db)


def test_get_missing_returns_none(db: Path) -> None:
    assert fx_store.get_fixture("nope", db) is None
