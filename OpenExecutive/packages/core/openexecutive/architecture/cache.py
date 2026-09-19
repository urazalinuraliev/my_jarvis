"""On-disk cache for generated architecture sections.

Reuses the same `./episodic_memory.db` SQLite file as
`openexecutive.memory.episodic` and `openexecutive.alerts.store`.
A separate table (`architecture_sections`) keeps the schemas
independent. The cache key per section is `effective_hash_for_section`
— a SHA-256 covering both the global facts and that section's KB
slice — so any drift in inputs forces regeneration.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from openexecutive.memory.episodic import DB_PATH as _EPISODIC_DB_PATH

logger = logging.getLogger(__name__)

DB_PATH = _EPISODIC_DB_PATH


class SectionContent(BaseModel):
    """The body of one architecture section, as rendered to the UI."""

    section_id: str
    markdown: str
    mermaid: str | None = None
    facts_hash: str
    generated_at: str  # ISO-8601 UTC


def _resolve_db_path(db_path: Path | None) -> Path:
    """Resolve to the current module-level DB_PATH if no explicit path
    was supplied. Using a function (rather than a default arg) means
    tests can `monkeypatch.setattr(cache_mod, "DB_PATH", tmp_path)` and
    have it actually take effect — default-arg binding happens once at
    function definition time, which made the patch a no-op."""
    return db_path if db_path is not None else DB_PATH


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
            CREATE TABLE IF NOT EXISTS architecture_sections (
                section_id TEXT PRIMARY KEY,
                facts_hash TEXT NOT NULL,
                markdown TEXT NOT NULL,
                mermaid TEXT,
                generated_at TEXT NOT NULL
            )
            """
        )


def get(section_id: str, db_path: Path | None = None) -> SectionContent | None:
    initialize_db(db_path)
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT section_id, facts_hash, markdown, mermaid, generated_at "
            "FROM architecture_sections WHERE section_id = ?",
            (section_id,),
        ).fetchone()
    if row is None:
        return None
    return SectionContent(
        section_id=row["section_id"],
        markdown=row["markdown"],
        mermaid=row["mermaid"],
        facts_hash=row["facts_hash"],
        generated_at=row["generated_at"],
    )


def put(content: SectionContent, db_path: Path | None = None) -> None:
    initialize_db(db_path)
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO architecture_sections
              (section_id, facts_hash, markdown, mermaid, generated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(section_id) DO UPDATE SET
              facts_hash = excluded.facts_hash,
              markdown = excluded.markdown,
              mermaid = excluded.mermaid,
              generated_at = excluded.generated_at
            """,
            (
                content.section_id,
                content.facts_hash,
                content.markdown,
                content.mermaid,
                content.generated_at,
            ),
        )


def is_fresh(section_id: str, current_hash: str, db_path: Path | None = None) -> bool:
    cached = get(section_id, db_path)
    return cached is not None and cached.facts_hash == current_hash


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
