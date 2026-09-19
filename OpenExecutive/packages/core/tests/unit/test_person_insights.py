"""Unit tests for the per-person brief insight cache + hash."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openexecutive.people import insights, insights_cache


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "insights.db"
    monkeypatch.setattr(insights_cache, "DB_PATH", path)
    insights_cache.initialize_db(path)
    return path


def _signals(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": "Bookkeeper",
        "is_principal": False,
        "status": "needs_reply",
        "awaiting_count": 0,
        "soonest_sla_at": None,
        "awaiting_reply_count": 2,
        "oldest_awaiting_reply_at": "2026-05-26T09:00:00+00:00",
        "overdue": True,
        "on_leave_until": None,
        "reachable_now": True,
        "next_window_at": None,
        "authority_scope": ["spend_lt_10k", "hiring_signoff"],
        "department_slugs": ["finance"],
        "last_contact_at": "2026-05-25T12:34:56+00:00",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Cache CRUD
# --------------------------------------------------------------------------- #

def test_get_returns_none_when_absent(db: Path) -> None:
    assert insights_cache.get(42, db_path=db) is None


def test_put_then_get_roundtrip(db: Path) -> None:
    insights_cache.put(
        insights_cache.PersonInsight(
            person_id=7, input_hash="abc", insight_text="Owes a reply since Tuesday",
            generated_at=insights_cache.utc_now_iso(),
        ),
        db_path=db,
    )
    got = insights_cache.get(7, db_path=db)
    assert got is not None
    assert got.insight_text == "Owes a reply since Tuesday"
    assert got.input_hash == "abc"


def test_put_upserts_on_conflict(db: Path) -> None:
    for text, h in (("old", "h1"), ("new", "h2")):
        insights_cache.put(
            insights_cache.PersonInsight(
                person_id=7, input_hash=h, insight_text=text,
                generated_at=insights_cache.utc_now_iso(),
            ),
            db_path=db,
        )
    got = insights_cache.get(7, db_path=db)
    assert got is not None
    assert got.insight_text == "new"
    assert got.input_hash == "h2"


def test_is_fresh_matches_hash(db: Path) -> None:
    insights_cache.put(
        insights_cache.PersonInsight(
            person_id=7, input_hash="hash-A", insight_text="x",
            generated_at=insights_cache.utc_now_iso(),
        ),
        db_path=db,
    )
    assert insights_cache.is_fresh(7, "hash-A", db_path=db) is True
    assert insights_cache.is_fresh(7, "hash-B", db_path=db) is False
    assert insights_cache.is_fresh(999, "hash-A", db_path=db) is False


# --------------------------------------------------------------------------- #
# Input hash
# --------------------------------------------------------------------------- #

def test_hash_stable_for_same_signals() -> None:
    assert insights.build_insight_input_hash(_signals()) == insights.build_insight_input_hash(_signals())


def test_hash_ignores_sub_hour_timestamp_jitter() -> None:
    """Second-level jitter within the same hour must NOT change the hash —
    otherwise the note would regenerate on nearly every request."""
    a = _signals(last_contact_at="2026-05-25T12:00:01+00:00")
    b = _signals(last_contact_at="2026-05-25T12:59:59+00:00")
    assert insights.build_insight_input_hash(a) == insights.build_insight_input_hash(b)


def test_hash_changes_when_status_changes() -> None:
    assert insights.build_insight_input_hash(_signals(status="needs_reply")) != \
        insights.build_insight_input_hash(_signals(status="clear"))


def test_hash_changes_across_the_hour_boundary() -> None:
    a = _signals(last_contact_at="2026-05-25T12:59:00+00:00")
    b = _signals(last_contact_at="2026-05-25T13:00:00+00:00")
    assert insights.build_insight_input_hash(a) != insights.build_insight_input_hash(b)


def test_hash_authority_scope_order_invariant() -> None:
    a = _signals(authority_scope=["spend_lt_10k", "hiring_signoff"])
    b = _signals(authority_scope=["hiring_signoff", "spend_lt_10k"])
    assert insights.build_insight_input_hash(a) == insights.build_insight_input_hash(b)
