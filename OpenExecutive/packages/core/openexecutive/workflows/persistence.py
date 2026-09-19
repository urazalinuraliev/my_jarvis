"""SQLite persistence for workflow runs.

Reuses the same DB file as `memory/episodic.py` (so a single backup covers
everything). The table is initialized lazily on first write.

Phase 6 additions
-----------------
Four columns added via idempotent ALTER:
  state_json     TEXT     — checkpoint dict (on_timeout, channel, etc.)
  awaiting_person_id INTEGER — person we're waiting on
  awaiting_until TEXT     — ISO timestamp for timeout
  resolution_json TEXT    — serialized WaitForHumanResolution on match

New status values beyond running/done/error:
  awaiting_human — paused, waiting for a human reply
  resolved       — human replied, resolution stored in resolution_json
  timed_out      — awaiting_until passed, timeout policy applied
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openexecutive.memory.episodic import DB_PATH, _get_conn


def _resolve(db_path: Path | None) -> Path:
    """Dynamic DB_PATH resolution — lets tests monkeypatch persistence.DB_PATH."""
    return db_path if db_path is not None else DB_PATH


def initialize_runs_db(db_path: Path | None = None) -> None:
    """Create the workflow_runs table if it doesn't exist. Idempotent."""
    with _get_conn(_resolve(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id        TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                title         TEXT NOT NULL,
                status        TEXT NOT NULL,
                inputs        TEXT NOT NULL,
                artifact      TEXT,
                error         TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS workflow_runs_workflow_idx "
            "ON workflow_runs (workflow_name, updated_at DESC)"
        )
        # Phase 6 additive columns — idempotent via PRAGMA + try/except pattern.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
        for col, ddl in (
            ("state_json", "TEXT"),
            ("awaiting_person_id", "INTEGER"),
            ("awaiting_until", "TEXT"),
            ("resolution_json", "TEXT"),
            # Artifacts gallery soft-delete: NULL = active, ISO ts = archived.
            ("archived_at", "TEXT"),
        ):
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE workflow_runs ADD COLUMN {col} {ddl}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise


def create_run(
    run_id: str,
    workflow_name: str,
    title: str,
    inputs: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    initialize_runs_db(db_path)  # _resolve happens inside
    now = datetime.now(UTC).isoformat()
    with _get_conn(_resolve(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO workflow_runs
                (run_id, workflow_name, title, status, inputs, created_at, updated_at)
            VALUES (?, ?, ?, 'running', ?, ?, ?)
            """,
            (run_id, workflow_name, title, json.dumps(inputs), now, now),
        )


def complete_run(
    run_id: str,
    artifact: str,
    db_path: Path | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(_resolve(db_path)) as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = 'done', artifact = ?, updated_at = ? "
            "WHERE run_id = ?",
            (artifact, now, run_id),
        )


def fail_run(
    run_id: str,
    error: str,
    db_path: Path | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    with _get_conn(_resolve(db_path)) as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = 'error', error = ?, updated_at = ? "
            "WHERE run_id = ?",
            (error, now, run_id),
        )


def get_run(run_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    if not _resolve(db_path).exists():
        return None
    with _get_conn(_resolve(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    out = dict(row)
    try:
        out["inputs"] = json.loads(out["inputs"]) if out["inputs"] else {}
    except json.JSONDecodeError:
        out["inputs"] = {}
    return out


def list_runs(
    workflow_name: str | None = None,
    limit: int = 100,
    db_path: Path | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Recent runs, newest-updated first. `workflow_name` and `status` are
    optional SQL filters — pushing `status` into the query (rather than letting
    callers filter the returned page) ensures a `status='done'` caller isn't
    starved when the most-recent `limit` rows are dominated by running/awaiting
    runs."""
    if not _resolve(db_path).exists():
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if workflow_name:
        clauses.append("workflow_name = ?")
        params.append(workflow_name)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    params.append(limit)
    with _get_conn(_resolve(db_path)) as conn:
        rows = conn.execute(
            "SELECT run_id, workflow_name, title, status, created_at, updated_at "
            f"FROM workflow_runs {where}ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def list_artifact_runs(
    limit: int = 200,
    db_path: Path | None = None,
    archived: bool = False,
) -> list[dict[str, Any]]:
    """Completed runs that produced an artifact, newest first.

    Powers the Executive Artifacts section. Mirrors `list_runs` — the heavy
    `artifact` body is intentionally excluded from the list query (fetch it
    per-run via `get_run`). Only `status='done'` runs with a non-empty
    artifact qualify; running/failed/awaiting runs have nothing to show. The
    `artifact != ''` guard keeps this list consistent with the artifacts
    detail route, which treats an empty body as "no artifact".

    `archived` selects which slice to return: the default (False) lists only
    active artifacts (`archived_at IS NULL`); True lists only archived ones,
    mirroring `alerts.store.list_artifact_alerts`.
    """
    if not _resolve(db_path).exists():
        return []
    archived_clause = (
        "AND archived_at IS NOT NULL" if archived else "AND archived_at IS NULL"
    )
    with _get_conn(_resolve(db_path)) as conn:
        rows = conn.execute(
            "SELECT run_id, workflow_name, title, status, created_at, updated_at, "
            "archived_at "
            "FROM workflow_runs "
            "WHERE artifact IS NOT NULL AND artifact != '' AND status = 'done' "
            f"{archived_clause} "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_run_archived(
    run_id: str, archived: bool, db_path: Path | None = None
) -> bool:
    """Archive (soft-hide) or restore a workflow-run artifact.

    Sets `archived_at` to the current time when archiving, or NULL when
    restoring. Returns True if a row was updated. Mirrors
    `alerts.store.set_alert_archived`.
    """
    if not _resolve(db_path).exists():
        return False
    now = datetime.now(UTC).isoformat() if archived else None
    with _get_conn(_resolve(db_path)) as conn:
        cur = conn.execute(
            "UPDATE workflow_runs SET archived_at = ? WHERE run_id = ?",
            (now, run_id),
        )
        return cur.rowcount > 0


def delete_run(run_id: str, db_path: Path | None = None) -> bool:
    if not _resolve(db_path).exists():
        return False
    with _get_conn(_resolve(db_path)) as conn:
        cur = conn.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Phase 6 — WaitForHuman checkpoint helpers
# ---------------------------------------------------------------------------

def save_checkpoint(
    run_id: str,
    state_json: str,
    awaiting_person_id: int | None,
    awaiting_until: datetime | None,
    db_path: Path | None = None,
) -> None:
    """Persist a WaitForHuman pause point and mark the run awaiting_human."""
    initialize_runs_db(db_path)  # _resolve happens inside
    now = datetime.now(UTC).isoformat()
    until_str = awaiting_until.isoformat() if awaiting_until else None
    with _get_conn(_resolve(db_path)) as conn:
        conn.execute(
            """
            UPDATE workflow_runs
               SET status = 'awaiting_human',
                   state_json = ?,
                   awaiting_person_id = ?,
                   awaiting_until = ?,
                   updated_at = ?
             WHERE run_id = ?
            """,
            (state_json, awaiting_person_id, until_str, now, run_id),
        )


def load_checkpoint(
    run_id: str,
    db_path: Path | None = None,
) -> tuple[str, int | None, datetime | None] | None:
    """Return (state_json, awaiting_person_id, awaiting_until) or None."""
    if not _resolve(db_path).exists():
        return None
    with _get_conn(_resolve(db_path)) as conn:
        row = conn.execute(
            "SELECT state_json, awaiting_person_id, awaiting_until "
            "FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    until: datetime | None = None
    if row[2]:
        try:
            until = datetime.fromisoformat(row[2])
            if until.tzinfo is None:
                until = until.replace(tzinfo=UTC)
        except ValueError:
            pass
    return (row[0], row[1], until)


def list_awaiting_runs(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Return all runs with status='awaiting_human'."""
    if not _resolve(db_path).exists():
        return []
    with _get_conn(_resolve(db_path)) as conn:
        rows = conn.execute(
            "SELECT run_id, workflow_name, title, awaiting_person_id, "
            "awaiting_until, state_json, resolution_json, updated_at "
            "FROM workflow_runs WHERE status = 'awaiting_human' "
            "ORDER BY updated_at"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(zip(
            ("run_id", "workflow_name", "title", "awaiting_person_id",
             "awaiting_until", "state_json", "resolution_json", "updated_at"),
            r,
            strict=False,
        ))
        result.append(d)
    return result


def store_resolution(
    run_id: str,
    resolution_json: str,
    db_path: Path | None = None,
) -> bool:
    """Store a resolution and mark the run resolved. Idempotent."""
    now = datetime.now(UTC).isoformat()
    with _get_conn(_resolve(db_path)) as conn:
        cur = conn.execute(
            """
            UPDATE workflow_runs
               SET status = 'resolved', resolution_json = ?, updated_at = ?
             WHERE run_id = ? AND status = 'awaiting_human'
            """,
            (resolution_json, now, run_id),
        )
        return cur.rowcount > 0


def mark_timed_out(run_id: str, db_path: Path | None = None) -> bool:
    """Transition awaiting_human → timed_out. Returns True if updated."""
    now = datetime.now(UTC).isoformat()
    with _get_conn(_resolve(db_path)) as conn:
        cur = conn.execute(
            "UPDATE workflow_runs SET status = 'timed_out', updated_at = ? "
            "WHERE run_id = ? AND status = 'awaiting_human'",
            (now, run_id),
        )
        return cur.rowcount > 0
