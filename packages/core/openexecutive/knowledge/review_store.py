from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("EPISODIC_DB_PATH", "./episodic_memory.db"))

PRIORITY_ORDER: dict[str, int] = {"high": 0, "normal": 1, "low": 2}


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class ContentType(StrEnum):
    BUILTIN = "builtin"
    EXTERNAL = "external"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ReviewItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_id: str
    content_type: ContentType
    domain: str
    filename: str
    status: ReviewStatus = ReviewStatus.PENDING
    priority: Priority = Priority.NORMAL
    reviewer_notes: str = ""
    reviewed_at: str | None = None
    registered_at: str
    last_modified_at: str


class Annotation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    annotation_id: str
    item_id: str
    domain: str
    correction: str
    is_active: bool = True
    created_at: str


@contextmanager
def _get_conn(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_item(row: sqlite3.Row) -> ReviewItem:
    return ReviewItem(
        item_id=row["item_id"],
        content_type=ContentType(row["content_type"]),
        domain=row["domain"],
        filename=row["filename"],
        status=ReviewStatus(row["status"]),
        priority=Priority(row["priority"]),
        reviewer_notes=row["reviewer_notes"] or "",
        reviewed_at=row["reviewed_at"],
        registered_at=row["registered_at"],
        last_modified_at=row["last_modified_at"],
    )


def _row_to_annotation(row: sqlite3.Row) -> Annotation:
    return Annotation(
        annotation_id=row["annotation_id"],
        item_id=row["item_id"],
        domain=row["domain"],
        correction=row["correction"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


def _migrate_review_items(conn: sqlite3.Connection) -> None:
    """In-place additive migration for the review_items table.

    Adds any column from the canonical schema that is missing on a legacy
    table. Raises ``sqlite3.OperationalError`` on any failure so the caller
    can fall back to a drop+recreate.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(review_items)")}
    for col, ddl in (
        ("domain", "TEXT NOT NULL DEFAULT ''"),
        ("item_id", "TEXT"),
        ("content_type", "TEXT"),
        ("filename", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("priority", "TEXT NOT NULL DEFAULT 'normal'"),
        ("reviewer_notes", "TEXT DEFAULT ''"),
        ("reviewed_at", "TEXT"),
        ("registered_at", "TEXT NOT NULL DEFAULT ''"),
        ("last_modified_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE review_items ADD COLUMN {col} {ddl}")


def _migrate_review_annotations(conn: sqlite3.Connection) -> None:
    """In-place additive migration for the review_annotations table.

    Adds any column from the canonical schema that is missing on a legacy
    table (older schemas used `id`/`annotation` instead of
    `annotation_id`/`correction`). Raises ``sqlite3.OperationalError`` on
    any failure so the caller can fall back to a drop+recreate.
    """
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(review_annotations)")
    }
    for col, ddl in (
        ("annotation_id", "TEXT"),
        ("item_id", "TEXT"),
        ("domain", "TEXT NOT NULL DEFAULT ''"),
        ("correction", "TEXT NOT NULL DEFAULT ''"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE review_annotations ADD COLUMN {col} {ddl}")


class ReviewStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    @staticmethod
    def initialize_db(db_path: Path = DB_PATH) -> None:
        """Create the review tables if missing and migrate legacy schemas.

        Completely robust: if ANY operational error occurs during schema
        creation or the additive migration (e.g. a legacy table with an
        incompatible column set that can't be ALTERed — "no such column:
        domain", "duplicate column name", a locked table, etc.), we drop
        the offending tables and recreate them from scratch. This is safe
        for the review store because:

          - review_items / review_annotations are caches of review state.
            The canonical rows (builtin knowledge registrations) are
            re-synced on startup by ``sync_builtin_registrations``.
          - Dropping and recreating loses only human review decisions
            (approved/rejected status, annotations) made on a legacy
            schema — an acceptable trade-off versus crashing the entire
            application on startup.

        A fresh DB (no tables) takes the fast path: executescript creates
        everything, the additive migration is a no-op, and we return.
        """
        canonical_ddl = """
            DROP TABLE IF EXISTS review_annotations;
            DROP TABLE IF EXISTS review_items;
            CREATE TABLE review_items (
                item_id          TEXT PRIMARY KEY,
                content_type     TEXT NOT NULL,
                domain           TEXT NOT NULL,
                filename         TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'pending',
                priority         TEXT NOT NULL DEFAULT 'normal',
                reviewer_notes   TEXT DEFAULT '',
                reviewed_at      TEXT,
                registered_at    TEXT NOT NULL,
                last_modified_at TEXT NOT NULL
            );
            CREATE INDEX idx_review_status ON review_items(status);
            CREATE INDEX idx_review_domain ON review_items(domain, status);
            CREATE TABLE review_annotations (
                annotation_id TEXT PRIMARY KEY,
                item_id       TEXT NOT NULL
                    REFERENCES review_items(item_id) ON DELETE CASCADE,
                domain        TEXT NOT NULL,
                correction    TEXT NOT NULL,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL
            );
            CREATE INDEX idx_annot_domain ON review_annotations(domain, is_active);
        """

        with _get_conn(db_path) as conn:
            # Fast path: no legacy tables exist — create the canonical schema
            # directly and return. No migration needed.
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name IN ('review_items', 'review_annotations')"
                )
            }
            if not existing:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS review_items (
                        item_id          TEXT PRIMARY KEY,
                        content_type     TEXT NOT NULL,
                        domain           TEXT NOT NULL,
                        filename         TEXT NOT NULL,
                        status           TEXT NOT NULL DEFAULT 'pending',
                        priority         TEXT NOT NULL DEFAULT 'normal',
                        reviewer_notes   TEXT DEFAULT '',
                        reviewed_at      TEXT,
                        registered_at    TEXT NOT NULL,
                        last_modified_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_review_status
                        ON review_items(status);
                    CREATE INDEX IF NOT EXISTS idx_review_domain
                        ON review_items(domain, status);
                    CREATE TABLE IF NOT EXISTS review_annotations (
                        annotation_id TEXT PRIMARY KEY,
                        item_id       TEXT NOT NULL
                            REFERENCES review_items(item_id) ON DELETE CASCADE,
                        domain        TEXT NOT NULL,
                        correction    TEXT NOT NULL,
                        is_active     INTEGER NOT NULL DEFAULT 1,
                        created_at    TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_annot_domain
                        ON review_annotations(domain, is_active);
                    """
                )
                return

            # Legacy tables exist — attempt an in-place additive migration.
            # If that fails for ANY reason, fall through to the drop+recreate
            # path below so startup never crashes.
            try:
                _migrate_review_items(conn)
                _migrate_review_annotations(conn)
                return
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "review_store: schema migration failed (%s: %s); "
                    "dropping review_items/review_annotations and recreating "
                    "canonical schema (review state lost, builtin "
                    "registrations re-synced on next startup)",
                    type(exc).__name__,
                    exc,
                )

            # Recreate from scratch. DROP + CREATE in a single executescript
            # so the FK ordering is always correct (annotations → items).
            conn.executescript(canonical_ddl)

    @staticmethod
    def sync_builtin_registrations(db_path: Path = DB_PATH) -> int:
        """INSERT OR IGNORE for every .md file in knowledge/builtin/ (excluding skills/).

        Idempotent — safe to call on every startup. Returns number of new registrations.
        """
        from openexecutive.knowledge.loader import BUILTIN_KNOWLEDGE_PATH

        now = datetime.now(UTC).isoformat()
        new_count = 0
        with _get_conn(db_path) as conn:
            for md_file in sorted(BUILTIN_KNOWLEDGE_PATH.rglob("*.md")):
                # Skip skills — they have separate management
                if "skills" in md_file.parts:
                    continue
                domain = md_file.parent.name
                filename = md_file.name
                item_id = f"builtin:{domain}:{filename}"
                result = conn.execute(
                    "INSERT OR IGNORE INTO review_items "
                    "(item_id, content_type, domain, filename, registered_at, last_modified_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (item_id, ContentType.BUILTIN.value, domain, filename, now, now),
                )
                new_count += result.rowcount
        return new_count

    @staticmethod
    def sync_external_registrations(
        ingested_source_ids: list[dict[str, Any]], db_path: Path = DB_PATH
    ) -> int:
        """INSERT OR IGNORE for all ingested OER sources. Returns new registration count."""
        now = datetime.now(UTC).isoformat()
        new_count = 0
        with _get_conn(db_path) as conn:
            for src in ingested_source_ids:
                item_id = f"external:{src['id']}"
                domain = src["domains"][0] if src.get("domains") else "general"
                result = conn.execute(
                    "INSERT OR IGNORE INTO review_items "
                    "(item_id, content_type, domain, filename, registered_at, last_modified_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (item_id, ContentType.EXTERNAL.value, domain, src["id"], now, now),
                )
                new_count += result.rowcount
        return new_count

    def register(
        self,
        item_id: str,
        content_type: ContentType,
        domain: str,
        filename: str,
    ) -> ReviewItem:
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO review_items "
                "(item_id, content_type, domain, filename, registered_at, last_modified_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, content_type.value, domain, filename, now, now),
            )
            row = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        return _row_to_item(row)

    def touch_modified(self, item_id: str) -> None:
        """Reset status on content edit: approved/rejected → needs_revision."""
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_items SET status = 'needs_revision', last_modified_at = ? "
                "WHERE item_id = ? AND status IN ('approved', 'rejected')",
                (now, item_id),
            )
            # Always bump last_modified_at even if no status change
            conn.execute(
                "UPDATE review_items SET last_modified_at = ? "
                "WHERE item_id = ? AND status NOT IN ('approved', 'rejected')",
                (now, item_id),
            )

    def delete_item(self, item_id: str) -> None:
        """Remove a review item and cascade-delete its annotations."""
        with _get_conn(self._db_path) as conn:
            conn.execute("DELETE FROM review_items WHERE item_id = ?", (item_id,))

    def update_notes(self, item_id: str, notes: str) -> ReviewItem:
        """Update reviewer notes without changing status or reviewed_at."""
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_items SET reviewer_notes = ?, last_modified_at = ? WHERE item_id = ?",
                (notes, now, item_id),
            )
            row = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Review item not found: {item_id}")
        return _row_to_item(row)

    def set_status(
        self,
        item_id: str,
        status: ReviewStatus,
        notes: str = "",
    ) -> ReviewItem:
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_items SET status = ?, reviewer_notes = ?, "
                "reviewed_at = ?, last_modified_at = ? WHERE item_id = ?",
                (status.value, notes, now, now, item_id),
            )
            row = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Review item not found: {item_id}")
        return _row_to_item(row)

    def set_priority(self, item_id: str, priority: Priority) -> ReviewItem:
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_items SET priority = ?, last_modified_at = ? WHERE item_id = ?",
                (priority.value, now, item_id),
            )
            row = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Review item not found: {item_id}")
        return _row_to_item(row)

    def bulk_approve(self, domain: str | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            if domain:
                result = conn.execute(
                    "UPDATE review_items SET status = 'approved', reviewed_at = ?, "
                    "last_modified_at = ? WHERE status = 'pending' AND domain = ?",
                    (now, now, domain),
                )
            else:
                result = conn.execute(
                    "UPDATE review_items SET status = 'approved', reviewed_at = ?, "
                    "last_modified_at = ? WHERE status = 'pending'",
                    (now, now),
                )
        return result.rowcount

    def get_rejected_filenames(self, content_type: ContentType) -> set[str]:
        # NOTE: this method no longer creates the table itself — schema
        # ownership lives in initialize_db(). A pre-existing DB created by an
        # older version of this module may lack the `domain` column; the
        # additive migration in initialize_db() adds it on startup. Calling
        # initialize_db() here is defensive only — it's idempotent and cheap
        # (all statements are IF NOT EXISTS), so a read path can never hit
        # "no such table" even if the caller forgot to init.
        ReviewStore.initialize_db(self._db_path)
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                "SELECT filename FROM review_items WHERE content_type = ? AND status = 'rejected'",
                (content_type.value,),
            ).fetchall()
        return {row["filename"] for row in rows}

    def get_rejected_source_ids(self) -> set[str]:
        return self.get_rejected_filenames(ContentType.EXTERNAL)

    def get_priority_map(self, content_type: ContentType) -> dict[str, str]:
        """Map filename → priority for approved items of a given content type."""
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                "SELECT filename, priority FROM review_items "
                "WHERE content_type = ? AND status = 'approved'",
                (content_type.value,),
            ).fetchall()
        return {row["filename"]: row["priority"] for row in rows}

    def list_items(
        self,
        status: ReviewStatus | None = None,
        domain: str | None = None,
        content_type: ContentType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewItem]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if content_type is not None:
            clauses.append("content_type = ?")
            params.append(content_type.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM review_items {where} "
                "ORDER BY registered_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_item(self, item_id: str) -> ReviewItem | None:
        with _get_conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def count_by_status(self) -> dict[str, int]:
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM review_items GROUP BY status"
            ).fetchall()
        counts: dict[str, int] = {s.value: 0 for s in ReviewStatus}
        for row in rows:
            counts[row["status"]] = row["n"]
        counts["total"] = sum(counts.values())
        return counts

    def add_annotation(self, item_id: str, domain: str, correction: str) -> Annotation:
        ann_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "INSERT INTO review_annotations "
                "(annotation_id, item_id, domain, correction, is_active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (ann_id, item_id, domain, correction, now),
            )
        return Annotation(
            annotation_id=ann_id,
            item_id=item_id,
            domain=domain,
            correction=correction,
            is_active=True,
            created_at=now,
        )

    def list_annotations(
        self,
        item_id: str | None = None,
        domains: list[str] | None = None,
        active_only: bool = True,
    ) -> list[Annotation]:
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("is_active = 1")
        if item_id is not None:
            clauses.append("item_id = ?")
            params.append(item_id)
        if domains is not None:
            placeholders = ",".join("?" * len(domains))
            clauses.append(f"domain IN ({placeholders})")
            params.extend(domains)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        
        with _get_conn(self._db_path) as conn:
            # Schema ownership lives in initialize_db(). The old inline
            # CREATE TABLE here (which defined `id`/`annotation` instead of
            # `annotation_id`/`correction` and lacked `domain`) has been
            # removed — it could create an incompatible table on a fresh DB
            # before initialize_db() ran. initialize_db() is idempotent, so
            # calling it defensively here guarantees the schema is current
            # without risking a duplicate-table error.
            ReviewStore.initialize_db(self._db_path)
            rows = conn.execute(
                f"SELECT * FROM review_annotations {where} ORDER BY created_at ASC",
                params,
            ).fetchall()
        return [_row_to_annotation(r) for r in rows]

    def toggle_annotation(self, annotation_id: str, is_active: bool) -> None:
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_annotations SET is_active = ? WHERE annotation_id = ?",
                (1 if is_active else 0, annotation_id),
            )

    def update_annotation(self, annotation_id: str, correction: str) -> None:
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "UPDATE review_annotations SET correction = ? WHERE annotation_id = ?",
                (correction, annotation_id),
            )

    def delete_annotation(self, annotation_id: str) -> None:
        with _get_conn(self._db_path) as conn:
            conn.execute(
                "DELETE FROM review_annotations WHERE annotation_id = ?", (annotation_id,)
            )
