"""On-disk cache for per-person brief insight notes.

Mirrors `openexecutive.architecture.cache`: a dedicated table in the shared
`./episodic_memory.db` SQLite file, keyed by `person_id` and validated against
an `input_hash` of that person's structured signals. When the signals change
(or the daily bucket rolls), the hash changes and the cached note is treated as
stale, so the /today route regenerates it in the background.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from openexecutive.memory import episodic as _episodic

logger = logging.getLogger(__name__)

# Explicit override slot. Left None in production so the cache follows the
# episodic DB dynamically (see _resolve_db_path) — capturing episodic.DB_PATH
# at import time the way architecture/cache.py does would make a test's
# `monkeypatch.setattr(episodic, "DB_PATH", ...)` silently miss this table,
# leaking rows into the real ./episodic_memory.db.
DB_PATH: Path | None = None


class PersonInsight(BaseModel):
    """A cached one-line insight note for a single Person."""

    person_id: int
    input_hash: str
    insight_text: str
    generated_at: str  # ISO-8601 UTC


def _resolve_db_path(db_path: Path | None) -> Path:
    """Resolve the DB path: explicit arg → module override → live episodic DB.

    Reading both `DB_PATH` and `episodic.DB_PATH` dynamically (not via
    default-arg binding) lets tests monkeypatch either and have it take effect.
    """
    if db_path is not None:
        return db_path
    if DB_PATH is not None:
        return DB_PATH
    return _episodic.DB_PATH


@contextmanager
def _get_conn(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    resolved = _resolve_db_path(db_path)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_db(db_path: Path | None = None) -> None:
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS person_insights (
                person_id INTEGER PRIMARY KEY,
                input_hash TEXT NOT NULL,
                insight_text TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )


def get(person_id: int, db_path: Path | None = None) -> PersonInsight | None:
    initialize_db(db_path)
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT person_id, input_hash, insight_text, generated_at "
            "FROM person_insights WHERE person_id = ?",
            (person_id,),
        ).fetchone()
    if row is None:
        return None
    return PersonInsight(
        person_id=row["person_id"],
        input_hash=row["input_hash"],
        insight_text=row["insight_text"],
        generated_at=row["generated_at"],
    )


def put(insight: PersonInsight, db_path: Path | None = None) -> None:
    initialize_db(db_path)
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO person_insights
              (person_id, input_hash, insight_text, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
              input_hash = excluded.input_hash,
              insight_text = excluded.insight_text,
              generated_at = excluded.generated_at
            """,
            (
                insight.person_id,
                insight.input_hash,
                insight.insight_text,
                insight.generated_at,
            ),
        )


def is_fresh(person_id: int, current_hash: str, db_path: Path | None = None) -> bool:
    cached = get(person_id, db_path)
    return cached is not None and cached.input_hash == current_hash


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
