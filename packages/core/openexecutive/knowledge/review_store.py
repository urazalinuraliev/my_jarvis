from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
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


_REVIEW_ITEMS_DDL = """
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
    )
"""
_REVIEW_ITEMS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_review_domain ON review_items(domain, status)",
)
_REVIEW_ANNOTATIONS_DDL = """
    CREATE TABLE IF NOT EXISTS review_annotations (
        annotation_id TEXT PRIMARY KEY,
        item_id       TEXT NOT NULL
            REFERENCES review_items(item_id) ON DELETE CASCADE,
        domain        TEXT NOT NULL,
        correction    TEXT NOT NULL,
        is_active     INTEGER NOT NULL DEFAULT 1,
        created_at    TEXT NOT NULL
    )
"""
_REVIEW_ANNOTATIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_annot_domain ON review_annotations(domain, is_active)",
)

_ITEM_COLUMNS: tuple[str, ...] = (
    "item_id", "content_type", "domain", "filename", "status", "priority",
    "reviewer_notes", "reviewed_at", "registered_at", "last_modified_at",
)
_ANNOTATION_COLUMNS: tuple[str, ...] = (
    "annotation_id", "item_id", "domain", "correction", "is_active", "created_at",
)

# Domain recorded for an external source whose manifest gave none — the same
# fallback ReviewStore.sync_external_registrations uses.
_EXTERNAL_DEFAULT_DOMAIN = "general"

# DB files whose review schema this process has already initialized. The read
# paths (retrieval) can run before the API lifespan's initialize_db — e.g. the
# CLI — so they initialize lazily, once per process per file.
_initialized_paths: set[Path] = set()


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def _column_shape(ddl: str, table: str) -> dict[str, tuple[int, int]]:
    """``(notnull, pk)`` for each column of the canonical *table*, read from its DDL."""
    with closing(sqlite3.connect(":memory:")) as mem:
        mem.execute(ddl)
        return {row[1]: (row[3], row[5]) for row in mem.execute(f"PRAGMA table_info({table})")}


_ITEMS_SHAPE = _column_shape(_REVIEW_ITEMS_DDL, "review_items")
_ANNOTATIONS_SHAPE = _column_shape(_REVIEW_ANNOTATIONS_DDL, "review_annotations")


def _is_current(cols: dict[str, sqlite3.Row], shape: dict[str, tuple[int, int]]) -> bool:
    """True when every canonical column exists with the same NOT NULL and primary-key role.

    A table that merely *has* the columns is not enough: older builds added
    them as nullable ``ADD COLUMN``s beside a different primary key.
    """
    for name, expected in shape.items():
        if name not in cols or (cols[name]["notnull"], cols[name]["pk"]) != expected:
            return False
    return all(not row["pk"] for name, row in cols.items() if name not in shape)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first_text(record: dict[str, Any], *names: str) -> str:
    """The first non-empty value among *names* (a legacy table may carry both an
    old column and an empty new one added beside it)."""
    return next((text for name in names if (text := _text(record.get(name)))), "")


def _enum_value(value: Any, enum_cls: type[StrEnum], default: StrEnum) -> str:
    text = _text(value)
    return text if text in {member.value for member in enum_cls} else default.value


def _salvage_item(record: dict[str, Any], now: str) -> tuple[Any, ...] | None:
    """One legacy review_items row as a canonical row, or None if it has no identity.

    ``item_id`` is ``builtin:{domain}:{filename}`` or ``external:{source id}``,
    so whichever of item_id / domain / filename is missing is recovered from
    the others.
    """
    item_id = _text(record.get("item_id"))
    domain = _text(record.get("domain"))
    filename = _text(record.get("filename"))
    content_type = _text(record.get("content_type"))
    if not item_id:
        if content_type == ContentType.EXTERNAL and filename:
            item_id = f"{ContentType.EXTERNAL}:{filename}"
        elif domain and filename:
            item_id = f"{ContentType.BUILTIN}:{domain}:{filename}"
        else:
            return None
    prefix, _, rest = item_id.partition(":")
    if prefix == ContentType.EXTERNAL:
        content_type = ContentType.EXTERNAL
        filename = filename or rest
        domain = domain or _EXTERNAL_DEFAULT_DOMAIN
    elif prefix == ContentType.BUILTIN:
        content_type = ContentType.BUILTIN
        parsed_domain, _, parsed_filename = rest.partition(":")
        domain = domain or parsed_domain
        filename = filename or parsed_filename
    return (
        item_id,
        _enum_value(content_type, ContentType, ContentType.BUILTIN),
        domain,
        filename,
        _enum_value(record.get("status"), ReviewStatus, ReviewStatus.PENDING),
        _enum_value(record.get("priority"), Priority, Priority.NORMAL),
        _text(record.get("reviewer_notes")),
        _text(record.get("reviewed_at")) or None,
        _text(record.get("registered_at")) or now,
        _text(record.get("last_modified_at")) or now,
    )


def _salvage_items(rows: list[sqlite3.Row], now: str) -> list[tuple[Any, ...]]:
    """Canonical review_items rows from a legacy table, one per item_id.

    A reviewed row beats a pending duplicate; otherwise the oldest row wins.
    """
    records = [dict(row) for row in rows]
    records.sort(
        key=lambda r: _enum_value(r.get("status"), ReviewStatus, ReviewStatus.PENDING)
        == ReviewStatus.PENDING
    )  # stable: keeps rowid order within each group
    salvaged: dict[str, tuple[Any, ...]] = {}
    for record in records:
        row = _salvage_item(record, now)
        if row is not None and row[0] not in salvaged:
            salvaged[row[0]] = row
    return list(salvaged.values())


def _salvage_annotations(
    rows: list[sqlite3.Row], item_domains: dict[str, str], now: str
) -> list[tuple[Any, ...]]:
    """Canonical review_annotations rows from a legacy table.

    Older builds used ``id`` / ``annotation``; annotations whose item no longer
    exists are left in the backup table only.
    """
    salvaged: dict[str, tuple[Any, ...]] = {}
    for record in (dict(row) for row in rows):
        annotation_id = _first_text(record, "annotation_id", "id")
        correction = _first_text(record, "correction", "annotation")
        item_id = _text(record.get("item_id"))
        if not annotation_id or not correction or item_id not in item_domains:
            continue
        salvaged.setdefault(annotation_id, (
            annotation_id,
            item_id,
            _text(record.get("domain")) or item_domains[item_id],
            correction,
            0 if _text(record.get("is_active")) in ("0", "false", "False") else 1,
            _text(record.get("created_at")) or now,
        ))
    return list(salvaged.values())


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    ddl: str,
    indexes: tuple[str, ...],
    columns: tuple[str, ...],
    salvage: Callable[[list[sqlite3.Row]], list[tuple[Any, ...]]],
    stamp: str,
) -> tuple[str, str, int, int]:
    """Back up *table*, recreate it from *ddl*, refill it with ``salvage(old rows)``.

    Returns ``(table, backup table, rows kept, rows before)``.
    """
    backup = f"{table}_legacy_{stamp}"
    n = 1
    while _table_columns(conn, backup):
        backup = f"{table}_legacy_{stamp}_{n}"
        n += 1
    conn.execute(f"CREATE TABLE {backup} AS SELECT * FROM {table}")
    old = conn.execute(f"SELECT * FROM {backup} ORDER BY rowid").fetchall()
    conn.execute(f"DROP TABLE {table}")
    conn.execute(ddl)
    for index in indexes:
        conn.execute(index)
    kept = salvage(old)
    placeholders = ", ".join("?" * len(columns))
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", kept
    )
    return table, backup, len(kept), len(old)


def _item_domains(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["item_id"]: row["domain"]
        for row in conn.execute("SELECT item_id, domain FROM review_items")
    }


def _rebuild_legacy_tables(
    conn: sqlite3.Connection, rebuild_items: bool, rebuild_annotations: bool
) -> None:
    """Rebuild legacy-shaped review tables in one transaction (see initialize_db)."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(UTC).isoformat()
    conn.commit()
    # Off for the rebuild: with foreign keys on, DROP TABLE review_items would
    # cascade-delete every annotation. The pragma is a no-op inside a
    # transaction, hence the commit above and the explicit BEGIN below.
    conn.execute("PRAGMA foreign_keys = OFF")
    report: list[tuple[str, str, int, int]] = []
    try:
        conn.execute("BEGIN")
        if rebuild_items:
            report.append(_rebuild_table(
                conn, "review_items", _REVIEW_ITEMS_DDL, _REVIEW_ITEMS_INDEXES,
                _ITEM_COLUMNS, lambda old: _salvage_items(old, now), stamp,
            ))
        if rebuild_annotations:
            # Annotations are salvaged against the items that exist, so the
            # items table must exist even when only annotations are legacy.
            conn.execute(_REVIEW_ITEMS_DDL)
            report.append(_rebuild_table(
                conn, "review_annotations", _REVIEW_ANNOTATIONS_DDL,
                _REVIEW_ANNOTATIONS_INDEXES, _ANNOTATION_COLUMNS,
                lambda old: _salvage_annotations(old, _item_domains(conn), now), stamp,
            ))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    for table, backup, kept_count, total in report:
        logger.warning(
            "review_store: rebuilt legacy %s to the current schema — kept %d of "
            "%d rows (deduplicated); the original rows are preserved in %s",
            table, kept_count, total, backup,
        )


class ReviewStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    @staticmethod
    def initialize_db(db_path: Path = DB_PATH) -> None:
        """Create the review tables, rebuilding any legacy-shaped ones.

        Older builds could leave tables of a different shape (an integer ``id``
        primary key, ``annotation`` instead of ``correction``, …). Adding the
        missing columns is not enough: without ``item_id`` as the primary key
        ``INSERT OR IGNORE`` never ignores, so every startup re-inserts the
        builtin registrations as duplicates, and NULL ``status`` values crash
        ``_row_to_item``. Such a table is rebuilt in a single transaction: its
        rows are first copied to ``<table>_legacy_<timestamp>`` (kept for the
        operator), the salvageable ones are carried over — deduplicated, human
        review decisions preferred — and the canonical table replaces it. Any
        error rolls the rebuild back and propagates; nothing is dropped
        without its backup.
        """
        with _get_conn(db_path) as conn:
            items = _table_columns(conn, "review_items")
            annotations = _table_columns(conn, "review_annotations")
            rebuild_items = bool(items) and not _is_current(items, _ITEMS_SHAPE)
            rebuild_annotations = bool(annotations) and not _is_current(
                annotations, _ANNOTATIONS_SHAPE
            )
            if rebuild_items or rebuild_annotations:
                _rebuild_legacy_tables(conn, rebuild_items, rebuild_annotations)
            for statement in (
                _REVIEW_ITEMS_DDL,
                *_REVIEW_ITEMS_INDEXES,
                _REVIEW_ANNOTATIONS_DDL,
                *_REVIEW_ANNOTATIONS_INDEXES,
            ):
                conn.execute(statement)
        _initialized_paths.add(Path(db_path).resolve())

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
        _ensure_schema(self._db_path)
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
        _ensure_schema(self._db_path)
        with _get_conn(self._db_path) as conn:
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


def _ensure_schema(db_path: Path) -> None:
    """Run ``ReviewStore.initialize_db`` once per process for *db_path*."""
    if Path(db_path).resolve() not in _initialized_paths:
        ReviewStore.initialize_db(db_path)
