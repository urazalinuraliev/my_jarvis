"""SQLite persistence for eval runs and user-added scenarios.

Shares the episodic_memory.db file (already on the `/data` volume in deploy)
so a single backup covers everything.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openexecutive.memory.episodic import DB_PATH, _get_conn


def initialize_eval_runs_db(db_path: Path = DB_PATH) -> None:
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                run_id       TEXT PRIMARY KEY,
                kind         TEXT NOT NULL,
                scenario_ids TEXT NOT NULL,
                status       TEXT NOT NULL,
                results      TEXT,
                passed       INTEGER,
                total        INTEGER,
                error        TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS eval_runs_kind_idx "
            "ON eval_runs (kind, updated_at DESC)"
        )


def create_eval_run(
    run_id: str,
    kind: str,
    scenario_ids: list[str],
    db_path: Path = DB_PATH,
) -> None:
    initialize_eval_runs_db(db_path)
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO eval_runs
                (run_id, kind, scenario_ids, status, results, passed, total, created_at, updated_at)
            VALUES (?, ?, ?, 'running', '[]', 0, ?, ?, ?)
            """,
            (run_id, kind, json.dumps(scenario_ids), len(scenario_ids), now, now),
        )


def append_scenario_result(
    run_id: str,
    result: dict[str, Any],
    passed_delta: int,
    db_path: Path = DB_PATH,
) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT results, passed FROM eval_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return
        results: list[dict[str, Any]] = json.loads(row["results"] or "[]")
        results.append(result)
        conn.execute(
            "UPDATE eval_runs SET results = ?, passed = ?, updated_at = ? WHERE run_id = ?",
            (json.dumps(results), (row["passed"] or 0) + passed_delta, now, run_id),
        )


def complete_eval_run(run_id: str, db_path: Path = DB_PATH) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            "UPDATE eval_runs SET status = 'done', updated_at = ? WHERE run_id = ?",
            (now, run_id),
        )


def fail_eval_run(run_id: str, error: str, db_path: Path = DB_PATH) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            "UPDATE eval_runs SET status = 'error', error = ?, updated_at = ? WHERE run_id = ?",
            (error, now, run_id),
        )


def cancel_eval_run(run_id: str, db_path: Path = DB_PATH) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            "UPDATE eval_runs SET status = 'canceled', updated_at = ? WHERE run_id = ?",
            (now, run_id),
        )


def get_eval_run(run_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    out = dict(row)
    try:
        out["results"] = json.loads(out["results"] or "[]")
        out["scenario_ids"] = json.loads(out["scenario_ids"] or "[]")
    except json.JSONDecodeError:
        out["results"] = []
        out["scenario_ids"] = []
    return out


def list_eval_runs(
    kind: str | None = None,
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with _get_conn(db_path) as conn:
        if kind:
            rows = conn.execute(
                "SELECT run_id, kind, status, passed, total, created_at, updated_at "
                "FROM eval_runs WHERE kind = ? ORDER BY updated_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT run_id, kind, status, passed, total, created_at, updated_at "
                "FROM eval_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_eval_run(run_id: str, db_path: Path = DB_PATH) -> bool:
    if not db_path.exists():
        return False
    with _get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM eval_runs WHERE run_id = ?", (run_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# User-added scenarios
# ---------------------------------------------------------------------------


def initialize_user_scenarios_db(db_path: Path = DB_PATH) -> None:
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_scenarios (
                id          TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                yaml        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )


def create_user_scenario(
    scenario_id: str,
    kind: str,
    yaml_text: str,
    db_path: Path = DB_PATH,
) -> None:
    """Insert a new user scenario. Raises sqlite3.IntegrityError on id collision."""
    initialize_user_scenarios_db(db_path)
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO eval_scenarios (id, kind, yaml, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scenario_id, kind, yaml_text, now, now),
        )


def update_user_scenario(
    scenario_id: str,
    kind: str,
    yaml_text: str,
    db_path: Path = DB_PATH,
) -> bool:
    """Update an existing user scenario. Returns False if not found."""
    if not db_path.exists():
        return False
    now = datetime.now(UTC).isoformat()
    with _get_conn(db_path) as conn:
        cur = conn.execute(
            "UPDATE eval_scenarios SET kind = ?, yaml = ?, updated_at = ? WHERE id = ?",
            (kind, yaml_text, now, scenario_id),
        )
        return cur.rowcount > 0


def delete_user_scenario(scenario_id: str, db_path: Path = DB_PATH) -> bool:
    if not db_path.exists():
        return False
    with _get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM eval_scenarios WHERE id = ?", (scenario_id,)
        )
        return cur.rowcount > 0


def get_user_scenario(
    scenario_id: str, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM eval_scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
    return dict(row) if row else None


def list_user_scenarios(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with _get_conn(db_path) as conn:
        # Defensive: table may not exist yet on a fresh deploy. Create it
        # if missing so `load_scenarios()` doesn't crash.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_scenarios (
                id          TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                yaml        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )
        rows = conn.execute(
            "SELECT id, kind, yaml, created_at, updated_at "
            "FROM eval_scenarios ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]
