"""Unit tests for the SME knowledge review store."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openexecutive.knowledge import review_schema
from openexecutive.knowledge.review_store import (
    Annotation,
    ContentType,
    Priority,
    ReviewItem,
    ReviewStatus,
    ReviewStore,
)


@pytest.fixture()
def store(tmp_path: Path) -> ReviewStore:
    db = tmp_path / "review.db"
    ReviewStore.initialize_db(db)
    return ReviewStore(db_path=db)


def _register_builtin(store: ReviewStore, domain: str = "finance", filename: str = "ratios.md") -> ReviewItem:
    item_id = f"builtin:{domain}:{filename}"
    return store.register(
        item_id=item_id,
        content_type=ContentType.BUILTIN,
        domain=domain,
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Register / idempotency
# ---------------------------------------------------------------------------


def test_register_creates_pending_item(store: ReviewStore) -> None:
    item = _register_builtin(store)
    assert item.status == ReviewStatus.PENDING
    assert item.priority == Priority.NORMAL
    assert item.content_type == ContentType.BUILTIN


def test_register_is_idempotent(store: ReviewStore) -> None:
    first = _register_builtin(store)
    # Approve, then re-register — should not reset the status
    store.set_status(first.item_id, ReviewStatus.APPROVED)
    second = store.register(
        item_id=first.item_id,
        content_type=ContentType.BUILTIN,
        domain="finance",
        filename="ratios.md",
    )
    assert second.status == ReviewStatus.APPROVED


# ---------------------------------------------------------------------------
# touch_modified transitions
# ---------------------------------------------------------------------------


def test_touch_modified_approved_becomes_needs_revision(store: ReviewStore) -> None:
    item = _register_builtin(store)
    store.set_status(item.item_id, ReviewStatus.APPROVED)
    store.touch_modified(item.item_id)
    updated = store.get_item(item.item_id)
    assert updated is not None
    assert updated.status == ReviewStatus.NEEDS_REVISION


def test_touch_modified_rejected_becomes_needs_revision(store: ReviewStore) -> None:
    item = _register_builtin(store)
    store.set_status(item.item_id, ReviewStatus.REJECTED)
    store.touch_modified(item.item_id)
    updated = store.get_item(item.item_id)
    assert updated is not None
    assert updated.status == ReviewStatus.NEEDS_REVISION


def test_touch_modified_pending_stays_pending(store: ReviewStore) -> None:
    item = _register_builtin(store)
    store.touch_modified(item.item_id)
    updated = store.get_item(item.item_id)
    assert updated is not None
    assert updated.status == ReviewStatus.PENDING


def test_touch_modified_needs_revision_stays(store: ReviewStore) -> None:
    item = _register_builtin(store)
    store.set_status(item.item_id, ReviewStatus.NEEDS_REVISION)
    store.touch_modified(item.item_id)
    updated = store.get_item(item.item_id)
    assert updated is not None
    assert updated.status == ReviewStatus.NEEDS_REVISION


# ---------------------------------------------------------------------------
# get_rejected_filenames
# ---------------------------------------------------------------------------


def test_get_rejected_filenames_returns_only_rejected(store: ReviewStore) -> None:
    item_a = _register_builtin(store, filename="ratios.md")
    item_b = _register_builtin(store, filename="fundraising.md")
    item_c = _register_builtin(store, filename="modeling.md")

    store.set_status(item_a.item_id, ReviewStatus.REJECTED)
    store.set_status(item_b.item_id, ReviewStatus.APPROVED)

    rejected = store.get_rejected_filenames(ContentType.BUILTIN)
    assert rejected == {"ratios.md"}
    assert "fundraising.md" not in rejected
    assert "modeling.md" not in rejected


def test_get_rejected_filenames_empty_when_none_rejected(store: ReviewStore) -> None:
    _register_builtin(store)
    assert store.get_rejected_filenames(ContentType.BUILTIN) == set()


def test_get_rejected_source_ids(store: ReviewStore) -> None:
    store.register(
        item_id="external:openstax-finance",
        content_type=ContentType.EXTERNAL,
        domain="finance",
        filename="openstax-finance",
    )
    store.set_status("external:openstax-finance", ReviewStatus.REJECTED)
    assert "openstax-finance" in store.get_rejected_source_ids()


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------


def test_set_priority(store: ReviewStore) -> None:
    item = _register_builtin(store)
    updated = store.set_priority(item.item_id, Priority.HIGH)
    assert updated.priority == Priority.HIGH


def test_get_priority_map_only_approved(store: ReviewStore) -> None:
    item_a = _register_builtin(store, filename="a.md")
    item_b = _register_builtin(store, filename="b.md")
    store.set_status(item_a.item_id, ReviewStatus.APPROVED)
    store.set_priority(item_a.item_id, Priority.HIGH)
    # item_b stays pending — should not appear in priority map

    pmap = store.get_priority_map(ContentType.BUILTIN)
    assert pmap.get("a.md") == "high"
    assert "b.md" not in pmap


# ---------------------------------------------------------------------------
# Bulk approve
# ---------------------------------------------------------------------------


def test_bulk_approve_all_pending(store: ReviewStore) -> None:
    for fn in ["a.md", "b.md", "c.md"]:
        _register_builtin(store, filename=fn)
    count = store.bulk_approve()
    assert count == 3
    for fn in ["a.md", "b.md", "c.md"]:
        item = store.get_item(f"builtin:finance:{fn}")
        assert item is not None
        assert item.status == ReviewStatus.APPROVED


def test_bulk_approve_domain_filter(store: ReviewStore) -> None:
    _register_builtin(store, domain="finance", filename="a.md")
    store.register(
        item_id="builtin:hr:b.md",
        content_type=ContentType.BUILTIN,
        domain="hr",
        filename="b.md",
    )
    count = store.bulk_approve(domain="finance")
    assert count == 1
    assert store.get_item("builtin:finance:a.md") is not None
    assert store.get_item("builtin:finance:a.md").status == ReviewStatus.APPROVED  # type: ignore[union-attr]
    assert store.get_item("builtin:hr:b.md") is not None
    assert store.get_item("builtin:hr:b.md").status == ReviewStatus.PENDING  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------


def test_add_and_list_annotations(store: ReviewStore) -> None:
    item = _register_builtin(store)
    ann = store.add_annotation(item.item_id, "finance", "Q3 burn rate is outdated")
    assert isinstance(ann, Annotation)
    assert ann.is_active is True

    listed = store.list_annotations(item_id=item.item_id)
    assert len(listed) == 1
    assert listed[0].correction == "Q3 burn rate is outdated"


def test_toggle_annotation(store: ReviewStore) -> None:
    item = _register_builtin(store)
    ann = store.add_annotation(item.item_id, "finance", "correction")
    store.toggle_annotation(ann.annotation_id, False)
    active = store.list_annotations(item_id=item.item_id, active_only=True)
    assert len(active) == 0
    all_anns = store.list_annotations(item_id=item.item_id, active_only=False)
    assert len(all_anns) == 1
    assert all_anns[0].is_active is False


def test_list_annotations_by_domain(store: ReviewStore) -> None:
    finance_item = _register_builtin(store, domain="finance", filename="a.md")
    hr_item = store.register(
        item_id="builtin:hr:b.md",
        content_type=ContentType.BUILTIN,
        domain="hr",
        filename="b.md",
    )
    store.add_annotation(finance_item.item_id, "finance", "finance note")
    store.add_annotation(hr_item.item_id, "hr", "hr note")

    finance_anns = store.list_annotations(domains=["finance"])
    assert len(finance_anns) == 1
    assert finance_anns[0].correction == "finance note"


def test_delete_annotation(store: ReviewStore) -> None:
    item = _register_builtin(store)
    ann = store.add_annotation(item.item_id, "finance", "to be deleted")
    store.delete_annotation(ann.annotation_id)
    assert store.list_annotations(item_id=item.item_id) == []


def test_delete_item_cascades_annotations(store: ReviewStore) -> None:
    item = _register_builtin(store)
    store.add_annotation(item.item_id, "finance", "note")
    store.delete_item(item.item_id)
    assert store.get_item(item.item_id) is None
    # Annotations should be cascade-deleted
    assert store.list_annotations(item_id=item.item_id) == []


# ---------------------------------------------------------------------------
# count_by_status
# ---------------------------------------------------------------------------


def test_count_by_status(store: ReviewStore) -> None:
    _register_builtin(store, filename="a.md")
    item_b = _register_builtin(store, filename="b.md")
    store.set_status(item_b.item_id, ReviewStatus.APPROVED)

    counts = store.count_by_status()
    assert counts["pending"] == 1
    assert counts["approved"] == 1
    assert counts["total"] == 2


# ---------------------------------------------------------------------------
# Legacy schemas
# ---------------------------------------------------------------------------


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _legacy_db(tmp_path: Path) -> Path:
    """A DB with the shapes older builds left behind: integer ``id`` primary
    key on review_items (so duplicates piled up), ``id``/``annotation`` on
    review_annotations, and NULL statuses."""
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE review_items (
                id INTEGER PRIMARY KEY, filename TEXT, content_type TEXT, status TEXT,
                priority TEXT, domain TEXT NOT NULL DEFAULT '', item_id TEXT,
                reviewer_notes TEXT DEFAULT '', reviewed_at TEXT,
                registered_at TEXT NOT NULL DEFAULT '', last_modified_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX idx_review_status ON review_items(status);
            CREATE TABLE review_annotations (
                id TEXT PRIMARY KEY, item_id TEXT, domain TEXT, annotation TEXT,
                is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        rows = [
            ("ratios.md", "builtin", None, None, "finance", "builtin:finance:ratios.md", "2026-09-01"),
            ("ratios.md", "builtin", "approved", "high", "finance", "builtin:finance:ratios.md", "2026-09-02"),
            ("ratios.md", "builtin", None, None, "finance", "builtin:finance:ratios.md", "2026-09-03"),
            ("oer-1", None, "bogus", None, "strategy", "external:oer-1", ""),
            ("orphan.md", "builtin", None, None, "hr", None, "2026-09-01"),
        ]
        conn.executemany(
            "INSERT INTO review_items (filename, content_type, status, priority, domain, item_id, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT INTO review_annotations (id, item_id, domain, annotation) "
            "VALUES ('a1', 'builtin:finance:ratios.md', 'finance', 'Use trailing twelve months')"
        )
        conn.execute(
            "INSERT INTO review_annotations (id, item_id, domain, annotation) "
            "VALUES ('a2', 'builtin:gone:x.md', 'finance', 'orphaned')"
        )
    return db


def test_legacy_tables_are_rebuilt_with_a_backup(tmp_path: Path) -> None:
    db = _legacy_db(tmp_path)
    ReviewStore.initialize_db(db)

    store = ReviewStore(db_path=db)
    items = {i.item_id: i for i in store.list_items()}
    # Duplicates collapse to one row; the human decision beats pending copies.
    # orphan.md had no item_id: it is rebuilt from its domain + filename.
    assert set(items) == {
        "builtin:finance:ratios.md", "external:oer-1", "builtin:hr:orphan.md"
    }
    assert items["builtin:finance:ratios.md"].status == ReviewStatus.APPROVED
    assert items["builtin:finance:ratios.md"].priority == Priority.HIGH
    # Invalid / NULL values fall back to defaults instead of crashing reads.
    assert items["external:oer-1"].status == ReviewStatus.PENDING
    assert items["external:oer-1"].content_type == ContentType.EXTERNAL

    annotations = store.list_annotations(active_only=False)
    assert [(a.annotation_id, a.correction) for a in annotations] == [
        ("a1", "Use trailing twelve months")
    ]

    # Every original row survives in the backup tables.
    backups = {t for t in _tables(db) if "_legacy_" in t}
    assert len(backups) == 2
    with sqlite3.connect(db) as conn:
        item_backup = next(t for t in backups if t.startswith("review_items_legacy_"))
        annot_backup = next(t for t in backups if t.startswith("review_annotations_legacy_"))
        assert conn.execute(f"SELECT COUNT(*) FROM {item_backup}").fetchone()[0] == 5
        assert conn.execute(f"SELECT COUNT(*) FROM {annot_backup}").fetchone()[0] == 2


def test_rebuilt_table_stops_duplicate_registrations(tmp_path: Path) -> None:
    db = _legacy_db(tmp_path)
    ReviewStore.initialize_db(db)
    store = ReviewStore(db_path=db)
    for _ in range(3):
        _register_builtin(store)
    assert len([i for i in store.list_items() if i.item_id == "builtin:finance:ratios.md"]) == 1


def test_initialize_is_a_no_op_on_a_current_schema(tmp_path: Path) -> None:
    db = tmp_path / "current.db"
    ReviewStore.initialize_db(db)
    store = ReviewStore(db_path=db)
    item = _register_builtin(store)
    store.set_status(item.item_id, ReviewStatus.REJECTED)

    ReviewStore.initialize_db(db)
    assert not any("_legacy_" in t for t in _tables(db))
    assert store.get_rejected_filenames(ContentType.BUILTIN) == {"ratios.md"}


def test_failed_rebuild_rolls_back_and_keeps_the_legacy_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _legacy_db(tmp_path)

    def broken_salvage(rows: object, now: str) -> list[tuple[object, ...]]:
        raise RuntimeError("salvage failed after the table was dropped")

    monkeypatch.setattr(review_schema, "_salvage_items", broken_salvage)
    with pytest.raises(RuntimeError):
        ReviewStore.initialize_db(db)

    assert not any("_legacy_" in t for t in _tables(db))
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(review_items)")}
        assert "id" in cols  # still the untouched legacy table
        assert conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 5


def test_read_path_initializes_a_fresh_db(tmp_path: Path) -> None:
    store = ReviewStore(db_path=tmp_path / "fresh.db")
    assert store.get_rejected_filenames(ContentType.BUILTIN) == set()
    assert store.list_annotations() == []


def test_annotations_survive_the_shape_older_migrations_left(tmp_path: Path) -> None:
    """An earlier additive migration put empty annotation_id / correction
    columns beside the real id / annotation ones; the real values must win."""
    db = tmp_path / "migrated.db"
    ReviewStore.initialize_db(db)
    _register_builtin(ReviewStore(db_path=db))
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            DROP TABLE review_annotations;
            CREATE TABLE review_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
                annotation TEXT NOT NULL, is_active INTEGER DEFAULT 1, created_at TEXT
            );
            INSERT INTO review_annotations (item_id, annotation)
                VALUES ('builtin:finance:ratios.md', 'Use trailing twelve months');
            ALTER TABLE review_annotations ADD COLUMN annotation_id TEXT;
            ALTER TABLE review_annotations ADD COLUMN domain TEXT NOT NULL DEFAULT '';
            ALTER TABLE review_annotations ADD COLUMN correction TEXT NOT NULL DEFAULT '';
        """)

    ReviewStore.initialize_db(db)
    annotations = ReviewStore(db_path=db).list_annotations(domains=["finance"])
    assert [(a.annotation_id, a.correction, a.domain) for a in annotations] == [
        ("1", "Use trailing twelve months", "finance")
    ]


def test_legacy_annotations_without_an_items_table(tmp_path: Path) -> None:
    db = tmp_path / "annotations_only.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE review_annotations (id TEXT PRIMARY KEY, item_id TEXT, "
            "domain TEXT, annotation TEXT, is_active INTEGER DEFAULT 1, created_at TEXT)"
        )
        conn.execute("INSERT INTO review_annotations (id, item_id, annotation) VALUES ('a', 'x', 'y')")

    ReviewStore.initialize_db(db)  # must not fail for want of review_items
    store = ReviewStore(db_path=db)
    assert store.list_items() == []
    assert store.list_annotations(active_only=False) == []  # its item is gone
    assert any(t.startswith("review_annotations_legacy_") for t in _tables(db))


def test_salvaged_rejection_keeps_filtering_retrieval(tmp_path: Path) -> None:
    """A legacy row without filename/domain columns is rebuilt from its
    item_id, so a rejected document stays rejected."""
    db = tmp_path / "narrow.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE review_items (id INTEGER PRIMARY KEY, item_id TEXT, "
            "content_type TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO review_items (item_id, content_type, status) "
            "VALUES ('builtin:strategy:d.md', 'builtin', 'rejected')"
        )

    ReviewStore.initialize_db(db)
    store = ReviewStore(db_path=db)
    assert store.get_rejected_filenames(ContentType.BUILTIN) == {"d.md"}
    item = store.get_item("builtin:strategy:d.md")
    assert item is not None and item.domain == "strategy"


def test_right_key_but_nullable_columns_is_rebuilt(tmp_path: Path) -> None:
    """item_id is the key, but the other columns were bolted on as nullable
    and hold NULLs that would crash every read."""
    db = tmp_path / "nullable.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE review_items (item_id TEXT PRIMARY KEY, filename TEXT)")
        conn.execute("INSERT INTO review_items VALUES ('builtin:hr:x.md', 'x.md')")
        for col in ("content_type", "domain", "status", "priority", "reviewer_notes",
                    "reviewed_at", "registered_at", "last_modified_at"):
            conn.execute(f"ALTER TABLE review_items ADD COLUMN {col} TEXT")

    ReviewStore.initialize_db(db)
    [item] = ReviewStore(db_path=db).list_items()
    assert (item.item_id, item.domain, item.status) == ("builtin:hr:x.md", "hr", ReviewStatus.PENDING)
