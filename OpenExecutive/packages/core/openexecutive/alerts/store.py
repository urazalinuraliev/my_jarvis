from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from openexecutive.alerts.models import (
    Alert,
    MuteTopic,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("EPISODIC_DB_PATH", "./episodic_memory.db"))


def _resolve_db_path(db_path: Path | None) -> Path:
    """Return the caller's path or the current module-level DB_PATH.

    Dynamic resolution lets tests monkeypatch DB_PATH without being foiled
    by default-argument binding (same pattern as people/store.py).
    """
    return db_path if db_path is not None else DB_PATH


@contextmanager
def _get_conn(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_resolve_db_path(db_path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_db(db_path: Path | None = None) -> None:
    with _get_conn(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                headline TEXT NOT NULL,
                body TEXT NOT NULL,
                suggested_action TEXT DEFAULT '',
                topic_tags TEXT DEFAULT '[]',
                channels_attempted TEXT DEFAULT '[]',
                channels_delivered TEXT DEFAULT '[]',
                dedup_key TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unread',
                created_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_status_created
                ON alerts(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alerts_dedup
                ON alerts(dedup_key, created_at DESC);
        """)
        # Additive migrations: idempotent via PRAGMA + try/except pattern.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
        for col, ddl in (
            # Phase 4: authority-gate routing column.
            ("routed_to_person_id", "INTEGER"),
            # Artifacts gallery soft-delete: NULL = active, ISO ts = archived.
            ("archived_at", "TEXT"),
        ):
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {ddl}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise
        conn.executescript("""

            CREATE TABLE IF NOT EXISTS mute_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                severity_threshold TEXT NOT NULL DEFAULT 'medium',
                quiet_hours_start TEXT DEFAULT '',
                quiet_hours_end TEXT DEFAULT '',
                quiet_hours_tz TEXT DEFAULT 'UTC',
                channels_enabled TEXT NOT NULL DEFAULT 'web,slack_dm,email,persisted',
                updated_at TEXT NOT NULL
            );

        """)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_alert(row: sqlite3.Row) -> Alert:
    d = dict(row)
    d["topic_tags"] = json.loads(d.get("topic_tags") or "[]")
    d["channels_attempted"] = json.loads(d.get("channels_attempted") or "[]")
    d["channels_delivered"] = json.loads(d.get("channels_delivered") or "[]")
    return Alert(**d)


def insert_alert(
    *,
    source: str,
    external_id: str,
    severity: str,
    headline: str,
    body: str,
    suggested_action: str = "",
    topic_tags: list[str] | None = None,
    dedup_key: str = "",
    routed_to_person_id: int | None = None,
    db_path: Path | None = None,
) -> int | None:
    """Insert a new alert. Returns alert id, or None if a duplicate was skipped."""
    tags = json.dumps(topic_tags or [])
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO alerts
                (external_id, source, severity, headline, body, suggested_action,
                 topic_tags, dedup_key, status, created_at, routed_to_person_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?)
            """,
            (
                external_id,
                source,
                severity,
                headline,
                body,
                suggested_action,
                tags,
                dedup_key,
                _now(),
                routed_to_person_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid


def update_delivery(
    alert_id: int,
    attempted: list[str],
    delivered: list[str],
    db_path: Path | None = None,
) -> None:
    with _get_conn(db_path) as conn:
        conn.execute(
            "UPDATE alerts SET channels_attempted = ?, channels_delivered = ? WHERE id = ?",
            (json.dumps(attempted), json.dumps(delivered), alert_id),
        )


def get_alert(alert_id: int, db_path: Path | None = None) -> Alert | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _row_to_alert(row) if row else None


def list_alerts(
    status: str | None = None,
    limit: int = 200,
    db_path: Path | None = None,
    exclude_source: str | None = None,
) -> list[Alert]:
    """Recent alerts, newest first. `status` and `exclude_source` are optional
    SQL filters — pushing `exclude_source` into the query (rather than letting
    callers drop rows from the returned page) ensures a caller that hides a
    source isn't starved when the most-recent `limit` rows are dominated by
    that source."""
    if not _resolve_db_path(db_path).exists():
        return []
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if exclude_source:
        clauses.append("source != ?")
        params.append(exclude_source)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    params.append(limit)
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts {where}ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_alert(r) for r in rows]


def recent_alerts(
    limit: int = 20,
    db_path: Path | None = None,
    exclude_source: str | None = None,
) -> list[Alert]:
    return list_alerts(
        status=None, limit=limit, db_path=db_path, exclude_source=exclude_source,
    )


def list_artifact_alerts(
    limit: int = 200, db_path: Path | None = None, archived: bool = False
) -> list[Alert]:
    """Alerts authored via `draft_artifact` (source='artifact'), newest first.

    Powers the Executive Artifacts section. Deliberately NOT filtered by
    status: a drafted artifact stays browsable after it's acked/dismissed
    out of the `/today` queue — surfacing it is the whole point of the
    Artifacts section (the row persists; `set_status` never deletes it).

    `archived` selects which slice to return: the default (False) lists only
    active artifacts (`archived_at IS NULL`); True lists only archived ones,
    so the gallery's Active / Archived views are clean swaps, not supersets.
    """
    if not _resolve_db_path(db_path).exists():
        return []
    archived_clause = (
        "AND archived_at IS NOT NULL" if archived else "AND archived_at IS NULL"
    )
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts WHERE source = 'artifact' {archived_clause} "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_alert(r) for r in rows]


def set_status(alert_id: int, status: str, db_path: Path | None = None) -> bool:
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE alerts SET status = ? WHERE id = ?", (status, alert_id)
        )
        return cursor.rowcount > 0


def get_alert_by_external(
    source: str, external_id: str, db_path: Path | None = None
) -> Alert | None:
    """Look up a single alert by its (source, external_id) pair.

    Used to find the companion briefing alert for a decision_instance
    (source='decision_scheduling', external_id='decision:{id}') — e.g. to
    assert it exists in tests or to inspect it before clearing it.
    """
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM alerts WHERE source = ? AND external_id = ? LIMIT 1",
            (source, external_id),
        ).fetchone()
    return _row_to_alert(row) if row else None


def set_status_by_external(
    source: str, external_id: str, status: str, db_path: Path | None = None
) -> bool:
    """Set the status of the alert keyed by (source, external_id).

    The clean primitive for clearing a decision_instance's companion
    briefing alert when the decision is resolved, without first SELECTing.
    Returns True if a row was updated (False — a harmless no-op — when no
    companion alert exists, e.g. a decision created before the bridge).
    """
    # Don't let a cold-system clear materialize a schemaless DB file; mirror
    # the existence guard on get_alert_by_external / list_alerts.
    if not _resolve_db_path(db_path).exists():
        return False
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE alerts SET status = ? WHERE source = ? AND external_id = ?",
            (status, source, external_id),
        )
        return cursor.rowcount > 0


def set_alert_archived(
    alert_id: int, archived: bool, db_path: Path | None = None
) -> bool:
    """Archive (soft-hide) or restore an alert-backed artifact.

    Sets `archived_at` to the current time when archiving, or NULL when
    restoring. Returns True if a row was updated. The artifact-source guard
    lives in the API layer (the route must not become a general alert mutator).
    """
    if not _resolve_db_path(db_path).exists():
        return False
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE alerts SET archived_at = ? WHERE id = ?",
            (_now() if archived else None, alert_id),
        )
        return cursor.rowcount > 0


def delete_alert(alert_id: int, db_path: Path | None = None) -> bool:
    if not _resolve_db_path(db_path).exists():
        return False
    with _get_conn(db_path) as conn:
        cursor = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        return cursor.rowcount > 0


# --- Mute topics ---


def add_mute(pattern: str, db_path: Path | None = None) -> int | None:
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern must be non-empty")
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO mute_topics (pattern, created_at) VALUES (?, ?)",
            (pattern, _now()),
        )
        if cursor.rowcount == 0:
            existing = conn.execute(
                "SELECT id FROM mute_topics WHERE pattern = ?", (pattern,)
            ).fetchone()
            return int(existing["id"]) if existing else None
        return int(cursor.lastrowid or 0)


def list_mutes(db_path: Path | None = None) -> list[MuteTopic]:
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM mute_topics ORDER BY created_at DESC"
        ).fetchall()
    return [MuteTopic(**dict(r)) for r in rows]


def delete_mute(mute_id: int, db_path: Path | None = None) -> bool:
    if not _resolve_db_path(db_path).exists():
        return False
    with _get_conn(db_path) as conn:
        cursor = conn.execute("DELETE FROM mute_topics WHERE id = ?", (mute_id,))
        return cursor.rowcount > 0


