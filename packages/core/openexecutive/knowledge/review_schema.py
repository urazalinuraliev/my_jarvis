"""SQLite schema of the SME review store, and its upgrade from legacy shapes.

Also home to the columns' value domains — :class:`ReviewStatus`,
:class:`ContentType`, :class:`Priority` — because salvaging legacy rows needs
them; ``review_store`` re-exports them for its callers.

:func:`ensure_review_schema` creates ``review_items`` / ``review_annotations``
and their indexes. Older builds could leave either table in a different shape
(an integer ``id`` primary key, ``annotation`` instead of ``correction``,
columns added later as nullable, …). Adding missing columns is
not enough: without ``item_id`` as the primary key ``INSERT OR IGNORE`` never
ignores, so every start-up re-registers the builtin files as duplicates, and
NULL ``status`` values crash every read.

Such a table is rebuilt in a single transaction:

1. its rows are copied to ``<table>_legacy_<timestamp>``, which is kept for
   the operator;
2. the table is recreated from the canonical DDL;
3. the old rows are normalized in Python and inserted — ids, domains and
   filenames are recovered from one another, a human review decision wins
   over a pending duplicate, and invalid values fall back to their defaults.

Any error rolls the whole rebuild back and propagates: nothing is dropped
without its backup.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from openexecutive.utils.names import first_unused

logger = logging.getLogger(__name__)


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


# --------------------------------------------------------------------------- #
# Canonical schema
# --------------------------------------------------------------------------- #

_ITEMS_DDL = """
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
_ITEMS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_review_domain ON review_items(domain, status)",
)
_ITEMS_COLUMNS: tuple[str, ...] = (
    "item_id", "content_type", "domain", "filename", "status", "priority",
    "reviewer_notes", "reviewed_at", "registered_at", "last_modified_at",
)

_ANNOTATIONS_DDL = """
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
_ANNOTATIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_annot_domain ON review_annotations(domain, is_active)",
)
_ANNOTATIONS_COLUMNS: tuple[str, ...] = (
    "annotation_id", "item_id", "domain", "correction", "is_active", "created_at",
)

# Domain recorded for an external source whose manifest names none.
EXTERNAL_DEFAULT_DOMAIN = "general"


def ensure_review_schema(conn: sqlite3.Connection) -> None:
    """Create the review tables and indexes, rebuilding legacy-shaped tables first."""
    items = _table_columns(conn, "review_items")
    annotations = _table_columns(conn, "review_annotations")
    rebuild_items = bool(items) and not _is_current(items, _ITEMS_SHAPE)
    rebuild_annotations = bool(annotations) and not _is_current(annotations, _ANNOTATIONS_SHAPE)
    if rebuild_items or rebuild_annotations:
        _rebuild_legacy_tables(conn, rebuild_items, rebuild_annotations)
    for statement in (_ITEMS_DDL, *_ITEMS_INDEXES, _ANNOTATIONS_DDL, *_ANNOTATIONS_INDEXES):
        conn.execute(statement)


# --------------------------------------------------------------------------- #
# Detecting a legacy shape
# --------------------------------------------------------------------------- #


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def _column_shape(ddl: str, table: str) -> dict[str, tuple[int, int]]:
    """``(notnull, pk)`` of each column of *table* as its DDL defines it."""
    with closing(sqlite3.connect(":memory:")) as mem:
        mem.execute(ddl)
        return {row[1]: (row[3], row[5]) for row in mem.execute(f"PRAGMA table_info({table})")}


_ITEMS_SHAPE = _column_shape(_ITEMS_DDL, "review_items")
_ANNOTATIONS_SHAPE = _column_shape(_ANNOTATIONS_DDL, "review_annotations")


def _is_current(cols: dict[str, sqlite3.Row], shape: dict[str, tuple[int, int]]) -> bool:
    """True when every canonical column exists with the same NOT NULL and
    primary-key role, and no other column is part of the primary key."""
    for name, expected in shape.items():
        if name not in cols or (cols[name]["notnull"], cols[name]["pk"]) != expected:
            return False
    return all(not row["pk"] for name, row in cols.items() if name not in shape)


# --------------------------------------------------------------------------- #
# Rebuilding
# --------------------------------------------------------------------------- #


def _rebuild_legacy_tables(
    conn: sqlite3.Connection, rebuild_items: bool, rebuild_annotations: bool
) -> None:
    """Rebuild the legacy-shaped review tables in one transaction."""
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
                conn, "review_items", _ITEMS_DDL, _ITEMS_INDEXES, _ITEMS_COLUMNS,
                lambda old: _salvage_items(old, now), stamp,
            ))
        if rebuild_annotations:
            # Annotations are salvaged against the existing items, so the items
            # table must exist even when only the annotations are legacy.
            conn.execute(_ITEMS_DDL)
            report.append(_rebuild_table(
                conn, "review_annotations", _ANNOTATIONS_DDL, _ANNOTATIONS_INDEXES,
                _ANNOTATIONS_COLUMNS,
                lambda old: _salvage_annotations(old, _item_domains(conn), now), stamp,
            ))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    for table, backup, kept, total in report:
        logger.warning(
            "review_store: rebuilt legacy %s to the current schema — kept %d of "
            "%d rows (deduplicated); the original rows are preserved in %s",
            table, kept, total, backup,
        )


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
    backup = first_unused(
        f"{table}_legacy_{stamp}", lambda name: bool(_table_columns(conn, name)), "_"
    )
    conn.execute(f"CREATE TABLE {backup} AS SELECT * FROM {table}")
    old = conn.execute(f"SELECT * FROM {backup} ORDER BY rowid").fetchall()
    conn.execute(f"DROP TABLE {table}")
    conn.execute(ddl)
    for index in indexes:
        conn.execute(index)
    kept = salvage(old)
    placeholders = ", ".join("?" * len(columns))
    conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", kept)
    return table, backup, len(kept), len(old)


def _item_domains(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["item_id"]: row["domain"]
        for row in conn.execute("SELECT item_id, domain FROM review_items")
    }


# --------------------------------------------------------------------------- #
# Salvaging legacy rows
# --------------------------------------------------------------------------- #


def _salvage_items(rows: list[sqlite3.Row], now: str) -> list[tuple[Any, ...]]:
    """Canonical review_items rows from a legacy table, one per item_id.

    A reviewed row beats a pending duplicate; otherwise the oldest row wins.
    """
    records = [dict(row) for row in rows]
    # Stable sort: rowid order is kept within the reviewed and pending groups.
    records.sort(key=lambda r: _status(r) == ReviewStatus.PENDING)
    salvaged: dict[str, tuple[Any, ...]] = {}
    for record in records:
        row = _salvage_item(record, now)
        if row is not None:
            salvaged.setdefault(row[0], row)
    return list(salvaged.values())


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
        domain = domain or EXTERNAL_DEFAULT_DOMAIN
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
        _status(record),
        _enum_value(record.get("priority"), Priority, Priority.NORMAL),
        _text(record.get("reviewer_notes")),
        _text(record.get("reviewed_at")) or None,
        _text(record.get("registered_at")) or now,
        _text(record.get("last_modified_at")) or now,
    )


def _salvage_annotations(
    rows: list[sqlite3.Row], item_domains: dict[str, str], now: str
) -> list[tuple[Any, ...]]:
    """Canonical review_annotations rows from a legacy table.

    Older builds used ``id`` / ``annotation`` (sometimes beside empty
    ``annotation_id`` / ``correction`` columns added later). Annotations whose
    item no longer exists stay in the backup table only.
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


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first_text(record: dict[str, Any], *names: str) -> str:
    """The first non-empty value among the columns *names*."""
    return next((text for name in names if (text := _text(record.get(name)))), "")


def _enum_value(value: Any, enum_cls: type[StrEnum], default: StrEnum) -> str:
    text = _text(value)
    return text if text in {member.value for member in enum_cls} else default.value


def _status(record: dict[str, Any]) -> str:
    return _enum_value(record.get("status"), ReviewStatus, ReviewStatus.PENDING)
