"""Tests for the trust-ledger CRUD, idempotency key dedup, and reliability reader."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.memory.decision_ledger import (
    STATUS_APPROVED_UNCHANGED,
    STATUS_APPROVED_WITH_EDIT,
    STATUS_REJECTED,
    STATUS_REVERSED,
    aggregate_reliability,
    create_decision_instance,
    get_class_mode,
    get_decision_instance,
    get_live_by_idem,
    list_instances,
    list_recent_resolved,
    mark_resolved,
    mark_reversed,
    record_high_severity_miss,
    set_class_mode,
)
from openexecutive.memory.episodic import initialize_db


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    return db_path


def _create(db: Path, *, idem: str | None = None, confidence: float = 0.8) -> int:
    return create_decision_instance(
        decision_class="meeting_scheduling",
        department="operations",
        originating_session_id="sess-1",
        proposed_payload={"title": "Sync", "start": "2025-06-01T10:00:00+00:00",
                          "end": "2025-06-01T11:00:00+00:00",
                          "attendee_emails": ["alice@example.com"]},
        idempotency_key=idem,
        gate_mode="propose",
        approver_person_id=None,
        confidence=confidence,
        db_path=db,
    )


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

def test_create_and_get(db: Path) -> None:
    iid = _create(db)
    inst = get_decision_instance(iid, db_path=db)
    assert inst is not None
    assert inst.id == iid
    assert inst.status == "proposed"
    assert inst.decision_class == "meeting_scheduling"


def test_get_missing_returns_none(db: Path) -> None:
    assert get_decision_instance(99999, db_path=db) is None


def test_mark_resolved_approve_unchanged(db: Path) -> None:
    iid = _create(db)
    ok = mark_resolved(iid, STATUS_APPROVED_UNCHANGED, external_event_id="evt-1", db_path=db)
    assert ok is True
    inst = get_decision_instance(iid, db_path=db)
    assert inst is not None
    assert inst.status == STATUS_APPROVED_UNCHANGED
    assert inst.external_event_id == "evt-1"
    assert inst.resolved_at is not None


def test_mark_resolved_compare_and_set(db: Path) -> None:
    """Double-ack must not change status a second time."""
    iid = _create(db)
    mark_resolved(iid, STATUS_APPROVED_UNCHANGED, db_path=db)
    ok2 = mark_resolved(iid, STATUS_REJECTED, db_path=db)
    assert ok2 is False
    assert get_decision_instance(iid, db_path=db).status == STATUS_APPROVED_UNCHANGED


def test_mark_reversed(db: Path) -> None:
    iid = _create(db)
    mark_resolved(iid, STATUS_APPROVED_UNCHANGED, external_event_id="e1", db_path=db)
    ok = mark_reversed(iid, reason="user cancelled", db_path=db)
    assert ok is True
    assert get_decision_instance(iid, db_path=db).status == STATUS_REVERSED


def test_list_recent_resolved_cross_class_newest_first(db: Path) -> None:
    """list_recent_resolved spans all classes, returns only terminal rows
    (resolved_at set), newest-resolved first, and honours the limit."""
    # A still-proposed row must NOT appear — it's a pending proposal, not activity.
    _create(db, idem="pending")
    # Three resolved rows, resolved in order a → b → c.
    a = _create(db, idem="a")
    b = _create(db, idem="b")
    c = _create(db, idem="c")
    import time
    mark_resolved(a, STATUS_APPROVED_UNCHANGED, db_path=db)
    time.sleep(0.01)
    mark_resolved(b, STATUS_REJECTED, db_path=db)
    time.sleep(0.01)
    mark_resolved(c, STATUS_APPROVED_WITH_EDIT, db_path=db)

    resolved = list_recent_resolved(limit=10, db_path=db)
    assert [r.id for r in resolved] == [c, b, a]  # newest resolved first
    assert all(r.resolved_at is not None for r in resolved)

    # Limit caps the result.
    assert [r.id for r in list_recent_resolved(limit=2, db_path=db)] == [c, b]


def test_list_recent_resolved_missing_db_returns_empty(tmp_path: Path) -> None:
    assert list_recent_resolved(db_path=tmp_path / "nope.db") == []


def test_record_high_severity_miss(db: Path) -> None:
    iid = _create(db)
    record_high_severity_miss(iid, reason="double-booked principal", db_path=db)
    inst = get_decision_instance(iid, db_path=db)
    assert inst.severity == "high"


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------

def test_idem_key_unique_index_raises(db: Path) -> None:
    import sqlite3
    _create(db, idem="key-abc")
    with pytest.raises(sqlite3.IntegrityError):
        _create(db, idem="key-abc")


def test_get_live_by_idem(db: Path) -> None:
    iid = _create(db, idem="key-xyz")
    found = get_live_by_idem("key-xyz", db_path=db)
    assert found is not None
    assert found.id == iid


def test_get_live_by_idem_returns_none_after_resolve(db: Path) -> None:
    iid = _create(db, idem="key-resolved")
    mark_resolved(iid, STATUS_APPROVED_UNCHANGED, db_path=db)
    assert get_live_by_idem("key-resolved", db_path=db) is None


def test_get_live_by_idem_returns_none_for_unknown(db: Path) -> None:
    assert get_live_by_idem("no-such-key", db_path=db) is None


# ---------------------------------------------------------------------------
# Class mode (propose / auto_execute)
# ---------------------------------------------------------------------------

def test_class_mode_default_propose(db: Path) -> None:
    assert get_class_mode("meeting_scheduling", db_path=db) == "propose"


def test_set_and_get_class_mode(db: Path) -> None:
    set_class_mode("meeting_scheduling", "auto_execute", db_path=db)
    assert get_class_mode("meeting_scheduling", db_path=db) == "auto_execute"


def test_set_class_mode_upsert(db: Path) -> None:
    set_class_mode("meeting_scheduling", "auto_execute", db_path=db)
    set_class_mode("meeting_scheduling", "propose", db_path=db)
    assert get_class_mode("meeting_scheduling", db_path=db) == "propose"


# ---------------------------------------------------------------------------
# Reliability reader math
# ---------------------------------------------------------------------------

def _seed_outcomes(db: Path, outcomes: list[str]) -> None:
    for i, outcome in enumerate(outcomes):
        iid = create_decision_instance(
            decision_class="meeting_scheduling",
            department="operations",
            originating_session_id=None,
            proposed_payload={"title": f"Meeting {i}"},
            idempotency_key=f"idem-{i}",
            gate_mode="propose",
            approver_person_id=None,
            confidence=0.9 if i % 2 == 0 else 0.5,
            db_path=db,
        )
        if outcome in (STATUS_APPROVED_UNCHANGED, STATUS_APPROVED_WITH_EDIT) or outcome == STATUS_REJECTED:
            mark_resolved(iid, outcome, db_path=db)
        elif outcome == STATUS_REVERSED:
            mark_resolved(iid, STATUS_APPROVED_UNCHANGED, db_path=db)
            mark_reversed(iid, db_path=db)


def test_reliability_card_zero_volume(db: Path) -> None:
    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)
    assert card.volume == 0
    assert card.unchanged_approval_rate == 0.0
    assert card.high_severity_misses == 0


def test_reliability_card_math(db: Path) -> None:
    outcomes = (
        [STATUS_APPROVED_UNCHANGED] * 47
        + [STATUS_APPROVED_WITH_EDIT] * 2
        + [STATUS_REJECTED] * 1
    )
    _seed_outcomes(db, outcomes)
    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)

    assert card.volume == 50
    # 47 / (47 + 2 + 1) = 0.94
    assert abs(card.unchanged_approval_rate - 0.94) < 0.01
    # 2 / 50 = 0.04
    assert abs(card.edit_rate - 0.04) < 0.01
    # 1 / 50 = 0.02
    assert abs(card.rejection_rate - 0.02) < 0.01
    assert card.reversal_rate == 0.0
    assert card.high_severity_misses == 0


def test_reliability_reversal_rate(db: Path) -> None:
    _seed_outcomes(db, [STATUS_APPROVED_UNCHANGED] * 5 + [STATUS_REVERSED] * 1)
    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)
    # reversed / (approved + executed) — approved_unchanged = 5, reversed = 1
    assert card.reversal_rate > 0.0


def test_reliability_window_excludes_old_rows(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows outside the window must not count."""
    import sqlite3
    old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO decision_instances
               (decision_class, created_at, department, proposed_payload_json,
                gate_mode, status)
               VALUES (?,?,?,?,?,?)""",
            ("meeting_scheduling", old_ts, "operations", '{"title":"old"}',
             "propose", STATUS_APPROVED_UNCHANGED),
        )
    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)
    assert card.volume == 0


def test_reliability_high_severity_counted(db: Path) -> None:
    iid = _create(db)
    record_high_severity_miss(iid, reason="test", db_path=db)
    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)
    assert card.high_severity_misses == 1


def test_reliability_calibration_buckets(db: Path) -> None:
    """Rows with confidence ~0.9 should land in the 0.8–0.9 bucket."""
    for i in range(5):
        iid = create_decision_instance(
            decision_class="meeting_scheduling",
            department="operations",
            originating_session_id=None,
            proposed_payload={"title": f"m{i}"},
            idempotency_key=f"cal-{i}",
            gate_mode="propose",
            approver_person_id=None,
            confidence=0.85,
            db_path=db,
        )
        mark_resolved(iid, STATUS_APPROVED_UNCHANGED, db_path=db)

    card = aggregate_reliability("meeting_scheduling", window_days=30, db_path=db)
    buckets_with_data = [b for b in card.calibration if b.count > 0]
    assert len(buckets_with_data) >= 1
    # All approved_unchanged in the 0.8–0.9 bucket → rate should be 1.0
    b = buckets_with_data[0]
    assert b.unchanged_rate == 1.0


# ---------------------------------------------------------------------------
# list_instances filter
# ---------------------------------------------------------------------------

def test_list_instances_status_filter(db: Path) -> None:
    iid1 = _create(db, idem="l1")
    iid2 = _create(db, idem="l2")
    mark_resolved(iid1, STATUS_REJECTED, db_path=db)

    proposed = list_instances("meeting_scheduling", status="proposed", db_path=db)
    assert len(proposed) == 1
    assert proposed[0].id == iid2

    all_items = list_instances("meeting_scheduling", db_path=db)
    assert len(all_items) == 2
