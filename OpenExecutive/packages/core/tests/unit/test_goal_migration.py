"""Tests for the Phase E schema migration: department_okrs → department_goals.

Starts from a hand-built DB in the OLD shape (table `department_okrs` with a
`quarter` column and no `period_type`), runs `initialize_db`, and asserts:
  • Old table is gone, new `department_goals` table exists
  • Column `quarter` renamed to `period_value`
  • New column `period_type` exists with default 'quarter' on all rows
  • Existing row data is preserved
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openexecutive.departments import store


def _build_old_shape_db(db_path: Path) -> None:
    """Create a database in the pre-Phase-E shape with one seeded row."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE departments (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                specialist_key TEXT,
                charter_mission TEXT NOT NULL DEFAULT '',
                charter_scope_json TEXT NOT NULL DEFAULT '[]',
                charter_out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                authority_level TEXT NOT NULL DEFAULT 'propose_only',
                head_person_id INTEGER,
                head_persona_slug TEXT,
                cadences_json TEXT NOT NULL DEFAULT '{}',
                headcount INTEGER,
                budget_usd REAL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE department_okrs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_slug TEXT NOT NULL,
                quarter TEXT NOT NULL,
                key_result TEXT NOT NULL,
                target TEXT NOT NULL,
                current TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'on_track',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (department_slug) REFERENCES departments(slug)
            );
            CREATE INDEX idx_okrs_dept ON department_okrs(department_slug);
        """)
        # Seed a department + an OKR so the migration has data to carry over.
        conn.execute(
            """
            INSERT INTO departments
              (slug, title, charter_mission, updated_at)
            VALUES ('finance', 'Finance', 'Steward capital', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO department_okrs
              (department_slug, quarter, key_result, target, current, status,
               created_at, updated_at)
            VALUES ('finance', 'Q2 2026', 'Close Series A', 'Funds wired', 'In progress',
                    'on_track', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _col_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture()
def old_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "old.db"
    _build_old_shape_db(db)
    monkeypatch.setattr(store, "DB_PATH", db)
    return db


def test_migration_renames_table_and_column(old_db: Path) -> None:
    store.initialize_db()

    conn = sqlite3.connect(str(old_db))
    try:
        assert _table_exists(conn, "department_goals")
        assert not _table_exists(conn, "department_okrs")
        cols = _col_names(conn, "department_goals")
        assert "period_value" in cols
        assert "period_type" in cols
        assert "quarter" not in cols
    finally:
        conn.close()


def test_migration_preserves_existing_data(old_db: Path) -> None:
    store.initialize_db()

    goals = store.list_goals("finance")
    assert len(goals) == 1
    g = goals[0]
    assert g.key_result == "Close Series A"
    assert g.period_type == "quarter"  # default backfill
    assert g.period_value == "Q2 2026"
    assert g.status == "on_track"


def test_migration_is_idempotent(old_db: Path) -> None:
    """Running initialize_db twice on the migrated DB must be a no-op."""
    store.initialize_db()
    store.initialize_db()
    goals = store.list_goals("finance")
    assert len(goals) == 1


def test_fresh_db_skips_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new DB created from scratch should land on the new schema directly."""
    fresh = tmp_path / "fresh.db"
    monkeypatch.setattr(store, "DB_PATH", fresh)
    store.initialize_db()

    conn = sqlite3.connect(str(fresh))
    try:
        assert _table_exists(conn, "department_goals")
        assert not _table_exists(conn, "department_okrs")
        cols = _col_names(conn, "department_goals")
        assert {"period_type", "period_value", "key_result", "target"} <= cols
    finally:
        conn.close()
