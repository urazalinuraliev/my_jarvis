"""Unit tests for the episodic → Honcho dept-peer mirror.

The mirror fires on a successful INSERT only (never on dedup hits) and
only when the row carries a non-empty, non-"general" department slug.
SQL remains the system of record — a Honcho failure here must never
roll back the episodic INSERT that just committed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openexecutive.memory import episodic


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Per-test isolated episodic SQLite DB."""
    db = tmp_path / "episodic.db"
    episodic.initialize_db(db)
    return db


@pytest.fixture
def mirror_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Spy on append_department_note inside honcho_client.

    Patches the source module — episodic.py imports lazily inside
    _mirror_to_dept_honcho, so patching on episodic.* misses the call.
    """
    calls: list[dict[str, Any]] = []

    def _spy(
        *,
        department_slug: str | None,
        kind: str,
        body: str,
        person_id: int | None = None,
    ) -> None:
        calls.append(
            {
                "department_slug": department_slug,
                "kind": kind,
                "body": body,
                "person_id": person_id,
            }
        )

    monkeypatch.setattr(
        "openexecutive.memory.honcho_client.append_department_note", _spy
    )
    return calls


# --------------------------------------------------------------------------- #
# store_decision
# --------------------------------------------------------------------------- #


def test_store_decision_with_dept_fires_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    episodic.store_decision(
        domain="finance",
        summary="Slow hiring through Q3",
        rationale="Runway is the binding constraint",
        department="finance",
        person_id=42,
        db_path=temp_db,
    )
    assert len(mirror_calls) == 1
    call = mirror_calls[0]
    assert call["department_slug"] == "finance"
    assert call["kind"] == "decision"
    assert call["person_id"] == 42
    assert "Slow hiring through Q3" in call["body"]
    assert "Rationale: Runway is the binding constraint" in call["body"]


def test_store_decision_without_dept_skips_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    episodic.store_decision(
        domain="finance",
        summary="x",
        department="",  # empty
        db_path=temp_db,
    )
    assert mirror_calls == []


def test_store_decision_general_dept_skips_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    """The literal 'general' dept means 'no scope' and has no dept peer."""
    episodic.store_decision(
        domain="strategy",
        summary="x",
        department="general",
        db_path=temp_db,
    )
    assert mirror_calls == []


def test_store_decision_dedup_does_not_double_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    """Two store calls in the 7-day dedup window with the same summary
    prefix → one INSERT, one mirror. The second call hits the dedup
    short-circuit and must NOT fire a second mirror."""
    for _ in range(2):
        episodic.store_decision(
            domain="finance",
            summary="Slow hiring through Q3",
            department="finance",
            session_id="s1",
            db_path=temp_db,
        )
    assert len(mirror_calls) == 1


# --------------------------------------------------------------------------- #
# store_initiative
# --------------------------------------------------------------------------- #


def test_store_initiative_new_row_fires_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    episodic.store_initiative(
        title="Hiring freeze",
        status="active",
        summary="Through end of Q3",
        department="finance",
        person_id=5,
        db_path=temp_db,
    )
    assert len(mirror_calls) == 1
    call = mirror_calls[0]
    assert call["kind"] == "initiative_update"
    assert call["department_slug"] == "finance"
    assert "Hiring freeze" in call["body"]
    assert "status=active" in call["body"]


def test_store_initiative_idempotent_upsert_does_not_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    """Same title + same status → upsert with no real change. The
    extraction layer may emit the same initiative on every turn during
    a long conversation; firing a mirror each time would spam the dept
    peer with identical notes."""
    for _ in range(3):
        episodic.store_initiative(
            title="Hiring freeze",
            status="active",
            department="finance",
            db_path=temp_db,
        )
    # First call inserts → 1 mirror. Subsequent calls are idempotent
    # upserts (status unchanged) → no additional mirrors.
    assert len(mirror_calls) == 1


def test_store_initiative_status_change_fires_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    """A real status transition (active → completed) should mirror."""
    episodic.store_initiative(
        title="Hiring freeze",
        status="active",
        department="finance",
        db_path=temp_db,
    )
    episodic.store_initiative(
        title="Hiring freeze",
        status="completed",
        department="finance",
        db_path=temp_db,
    )
    assert len(mirror_calls) == 2
    assert "status=active" in mirror_calls[0]["body"]
    assert "status=completed" in mirror_calls[1]["body"]


# --------------------------------------------------------------------------- #
# store_advice
# --------------------------------------------------------------------------- #


def test_store_advice_with_dept_fires_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    episodic.store_advice(
        domain="marketing",
        query_summary="Should we double GTM spend?",
        advice_summary="No — capital efficiency matters more than top-of-funnel right now",
        department="marketing",
        person_id=7,
        db_path=temp_db,
    )
    assert len(mirror_calls) == 1
    call = mirror_calls[0]
    assert call["kind"] == "advice"
    assert call["department_slug"] == "marketing"
    assert "double GTM spend" in call["body"]
    assert call["person_id"] == 7


def test_store_advice_dedup_does_not_double_mirror(
    temp_db: Path, mirror_calls: list[dict[str, Any]]
) -> None:
    for _ in range(2):
        episodic.store_advice(
            domain="marketing",
            query_summary="q",
            advice_summary="same advice text " * 10,
            department="marketing",
            session_id="s1",
            db_path=temp_db,
        )
    assert len(mirror_calls) == 1


# --------------------------------------------------------------------------- #
# Honcho failure must not break the episodic write
# --------------------------------------------------------------------------- #


def test_mirror_failure_does_not_rollback_sql_write(
    temp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If append_department_note raises (theoretical — the wrapper is
    supposed to swallow), the SQL row must still be visible. The mirror
    runs AFTER the connection context manager exits, so the INSERT is
    already committed."""
    def boom(**_: Any) -> None:
        raise RuntimeError("honcho boom")

    monkeypatch.setattr(
        "openexecutive.memory.honcho_client.append_department_note", boom
    )

    # Currently the mirror does NOT catch — it relies on the wrapper's
    # own swallowing. If that contract changes, this test will surface
    # the exception and the regression will be obvious.
    with pytest.raises(RuntimeError, match="honcho boom"):
        episodic.store_decision(
            domain="finance",
            summary="x",
            department="finance",
            db_path=temp_db,
        )

    # The SQL row is still visible despite the post-commit raise.
    rows = episodic.list_decisions(db_path=temp_db)
    assert len(rows) == 1
    assert rows[0].summary == "x"
