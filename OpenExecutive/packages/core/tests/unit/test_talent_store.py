"""Store-level tests for the talent / executive-search core."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, EngagementStatus


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _seed_engagement(
    must_haves: str = "10+ yrs upstream", department: str = "Drilling"
) -> int:
    return talent_store.upsert_engagement(
        role_title="VP Drilling", department=department, must_haves=must_haves
    )


def test_initialize_db_idempotent(db: Path) -> None:
    talent_store.initialize_db()
    talent_store.initialize_db()
    assert talent_store.list_engagements() == []


def test_initialize_db_resets_legacy_clients_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A legacy DB carrying a `clients` table (the old external-client model) is
    # detected and the talent tables are dropped + rebuilt in the in-house shape.
    import sqlite3

    path = tmp_path / "legacy.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE engagements (id INTEGER PRIMARY KEY, client_id INTEGER, role_title TEXT);"
        "INSERT INTO clients (name) VALUES ('Legacy Co');"
    )
    conn.commit()
    conn.close()

    talent_store.initialize_db()

    with sqlite3.connect(str(path)) as check:
        tables = {
            r[0]
            for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Legacy clients table is gone; engagements has the new `department` col.
        assert "clients" not in tables
        cols = {r[1] for r in check.execute("PRAGMA table_info(engagements)").fetchall()}
        assert "department" in cols
        assert "client_id" not in cols

    # And it's empty (rebuilt fresh, no carry-over rows).
    assert talent_store.list_engagements() == []


def test_engagement_crud_and_filter(db: Path) -> None:
    eid = _seed_engagement()
    eng = talent_store.get_engagement(eid)
    assert eng is not None
    assert eng.role_title == "VP Drilling"
    assert eng.department == "Drilling"
    assert eng.status == EngagementStatus.OPEN

    # A second engagement to verify listing returns both.
    talent_store.upsert_engagement(role_title="CFO", department="Finance")

    engagements = talent_store.list_engagements()
    assert len(engagements) == 2
    assert {e.role_title for e in engagements} == {"VP Drilling", "CFO"}


def test_engagement_update_preserves_department(db: Path) -> None:
    eid = _seed_engagement()
    talent_store.upsert_engagement(
        role_title="VP Drilling & Completions",
        department="Drilling",
        engagement_id=eid,
    )
    eng = talent_store.get_engagement(eid)
    assert eng is not None
    assert eng.role_title == "VP Drilling & Completions"
    assert eng.department == "Drilling"


def test_engagement_status_transition(db: Path) -> None:
    eid = _seed_engagement()
    assert talent_store.set_engagement_status(eid, EngagementStatus.FILLED) is True
    assert talent_store.get_engagement(eid).status == EngagementStatus.FILLED  # type: ignore[union-attr]


def test_engagement_archive_excluded_by_default(db: Path) -> None:
    eid = _seed_engagement()
    assert talent_store.archive_engagement(eid) is True
    assert talent_store.list_engagements() == []
    assert len(talent_store.list_engagements(include_archived=True)) == 1
    assert talent_store.archive_engagement(9999) is False


def test_candidate_crud_and_filters(db: Path) -> None:
    eid = _seed_engagement()
    cand_id = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", current_title="Drilling Director"
    )
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None
    assert cand.full_name == "Dana Cole"
    assert cand.stage == CandidateStage.LEAD
    assert cand.fit_score is None

    talent_store.upsert_candidate(
        engagement_id=eid, full_name="Sam Reyes", stage=CandidateStage.INTERVIEWED
    )
    assert len(talent_store.list_candidates(engagement_id=eid)) == 2
    interviewed = talent_store.list_candidates(
        engagement_id=eid, stage=CandidateStage.INTERVIEWED
    )
    assert len(interviewed) == 1
    assert interviewed[0].full_name == "Sam Reyes"


def test_set_candidate_stage(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    assert talent_store.set_candidate_stage(cid, CandidateStage.OFFER) is True
    assert talent_store.get_candidate(cid).stage == CandidateStage.OFFER  # type: ignore[union-attr]


def test_record_screening_persists_and_advances_lead(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    ok = talent_store.record_screening(cid, fit_score=82, summary="Strong cycle-tested fit.")
    assert ok is True
    cand = talent_store.get_candidate(cid)
    assert cand is not None
    assert cand.fit_score == 82
    assert cand.screening_summary == "Strong cycle-tested fit."
    assert cand.stage == CandidateStage.SCREENED  # advanced from lead


def test_record_screening_does_not_drag_back_advanced_candidate(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Sam Reyes", stage=CandidateStage.INTERVIEWED
    )
    talent_store.record_screening(cid, fit_score=70, summary="Re-screen.")
    # Stays interviewed — a re-screen must not reset an advanced candidate.
    assert talent_store.get_candidate(cid).stage == CandidateStage.INTERVIEWED  # type: ignore[union-attr]


def test_record_screening_rejects_out_of_range(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    with pytest.raises(ValueError):
        talent_store.record_screening(cid, fit_score=150, summary="bad")


def test_record_screening_unknown_candidate_returns_false(db: Path) -> None:
    assert (
        talent_store.record_screening(9999, fit_score=50, summary="x") is False
    )


def test_record_screening_skips_archived_candidate(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    talent_store.archive_candidate(cid)
    # A screen landing after the candidate was archived must be a no-op.
    assert talent_store.record_screening(cid, fit_score=88, summary="late") is False
    cand = talent_store.list_candidates(
        engagement_id=eid, include_archived=True
    )[0]
    assert cand.fit_score is None
    assert cand.screening_summary == ""


def test_archive_candidate(db: Path) -> None:
    eid = _seed_engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    assert talent_store.archive_candidate(cid) is True
    assert talent_store.list_candidates(engagement_id=eid) == []
    assert len(talent_store.list_candidates(engagement_id=eid, include_archived=True)) == 1


def test_archive_engagement_is_soft_and_keeps_candidates(db: Path) -> None:
    # Archiving an engagement does not remove its candidate rows; soft-delete is
    # independent per entity (matches people semantics).
    eid = _seed_engagement()
    talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    talent_store.archive_engagement(eid)
    # Engagement still resolvable directly; candidate rows untouched.
    assert talent_store.get_engagement(eid) is not None
    assert len(talent_store.list_candidates(engagement_id=eid)) == 1


def test_reads_on_missing_db_return_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Before initialize_db / before any file exists, reads degrade to empty
    # rather than raising — mirrors people.store behaviour.
    monkeypatch.setattr(talent_store, "DB_PATH", tmp_path / "nope.db")
    assert talent_store.list_engagements() == []
    assert talent_store.list_candidates() == []
    assert talent_store.get_engagement(1) is None
