"""Tests for the shared talent briefing digest (briefing/talent_digest.py).

Covers the stage rollup math (needs-screening / offers-out / stalled), the
exclusion of terminal engagements, and the chat-digest text — the logic both
/today and the chat <briefing> block depend on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.briefing import talent_digest
from openexecutive.briefing.talent_digest import (
    STALL_THRESHOLD_DAYS,
    build_talent_brief_items,
    format_talent_for_prompt,
)
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, EngagementStatus


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _backdate_candidate(candidate_id: int, days: int) -> None:
    """Force a candidate's updated_at to *days* in the past (for stall tests)."""
    from datetime import UTC, datetime, timedelta

    ts = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with talent_store._get_conn() as conn:
        conn.execute(
            "UPDATE candidates SET updated_at = ? WHERE id = ?", (ts, candidate_id)
        )


def test_empty_db_returns_nothing(db: Path) -> None:
    assert build_talent_brief_items() == []
    assert format_talent_for_prompt() == ""


def test_rollup_counts(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="VP Drilling", department="Drilling")

    # Two leads (need screening), one offer out, one placed (terminal).
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead A", stage=CandidateStage.LEAD)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead B", stage=CandidateStage.LEAD)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Offeree", stage=CandidateStage.OFFER)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Hired", stage=CandidateStage.PLACED)

    items = build_talent_brief_items()
    assert len(items) == 1
    item = items[0]
    assert item.engagement_id == eid
    assert item.department == "Drilling"
    assert item.role_title == "VP Drilling"
    assert item.candidate_count == 4
    assert item.needs_screening == 2
    assert item.offers_out == 1
    assert item.stage_counts == {"lead": 2, "offer": 1, "placed": 1}
    # Fresh candidates aren't stalled.
    assert item.stalled_count == 0


def test_stalled_only_counts_active_stages(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="CFO", department="Finance")

    # An interviewed candidate gone cold past the threshold → stalled.
    cold = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Cold Interview", stage=CandidateStage.INTERVIEWED
    )
    _backdate_candidate(cold, STALL_THRESHOLD_DAYS + 3)

    # A placed candidate that is also old must NOT count as stalled (terminal).
    placed = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Old Hire", stage=CandidateStage.PLACED
    )
    _backdate_candidate(placed, STALL_THRESHOLD_DAYS + 30)

    # A fresh lead is active but not yet stalled.
    talent_store.upsert_candidate(engagement_id=eid, full_name="Fresh Lead", stage=CandidateStage.LEAD)

    item = build_talent_brief_items()[0]
    assert item.stalled_count == 1


def test_terminal_engagements_excluded(db: Path) -> None:
    open_eid = talent_store.upsert_engagement(role_title="Open Role")
    filled_eid = talent_store.upsert_engagement(role_title="Filled Role")
    talent_store.set_engagement_status(filled_eid, EngagementStatus.FILLED)

    items = build_talent_brief_items()
    ids = {i.engagement_id for i in items}
    assert open_eid in ids
    assert filled_eid not in ids


def test_format_for_prompt_text(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="VP Drilling", department="Drilling")
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead A", stage=CandidateStage.LEAD)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Offeree", stage=CandidateStage.OFFER)

    text = format_talent_for_prompt()
    assert f"[eng {eid}]" in text
    # In-house line is "[eng N] <role> · <department> (<status>): ..." — no client.
    assert "VP Drilling · Drilling (open)" in text
    assert "Meridian" not in text
    assert "2 candidates" in text
    assert "1 need screening" in text
    assert "1 offer out" in text


def test_format_for_prompt_omits_department_when_blank(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="CFO")
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead A", stage=CandidateStage.LEAD)

    text = format_talent_for_prompt()
    # No department → no " · " separator before the status.
    assert f"[eng {eid}] CFO (open)" in text


def test_build_swallows_store_errors(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_: object) -> list:
        raise RuntimeError("store down")

    monkeypatch.setattr(talent_digest, "_MAX_ENGAGEMENTS", 25)
    monkeypatch.setattr(talent_store, "list_engagements", _boom)
    # Must not raise — a talent hiccup can never break a brief.
    assert build_talent_brief_items() == []
    assert format_talent_for_prompt() == ""


# --------------------------------------------------------------------------- #
# Offers expiring soon
# --------------------------------------------------------------------------- #

def _seed_extended_offer(engagement_id: int, candidate_id: int, *, expires_in_hours: float) -> int:
    from datetime import UTC, datetime, timedelta

    from openexecutive.talent.models import OfferStatus

    oid = talent_store.create_offer(
        candidate_id=candidate_id, engagement_id=engagement_id, comp_summary="x"
    )
    expiry = (datetime.now(UTC) + timedelta(hours=expires_in_hours)).isoformat()
    talent_store.set_offer_status(oid, OfferStatus.EXTENDED, expires_at=expiry)
    return oid


def test_offers_expiring_soon_counts_window_and_past(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="VP Drilling")
    near = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Near", stage=CandidateStage.OFFER
    )
    overdue = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Overdue", stage=CandidateStage.OFFER
    )
    far = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Far", stage=CandidateStage.OFFER
    )
    _seed_extended_offer(eid, near, expires_in_hours=24)     # inside the 72h window
    _seed_extended_offer(eid, overdue, expires_in_hours=-6)  # past expiry, no decision
    _seed_extended_offer(eid, far, expires_in_hours=24 * 10)  # well outside

    items = build_talent_brief_items()
    assert items[0].offers_expiring_soon == 2

    text = format_talent_for_prompt()
    assert "2 offers expiring ≤3d" in text


def test_decided_offers_do_not_count_as_expiring(db: Path) -> None:
    from openexecutive.talent.models import OfferStatus

    eid = talent_store.upsert_engagement(role_title="CFO")
    cid = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Done", stage=CandidateStage.OFFER
    )
    oid = _seed_extended_offer(eid, cid, expires_in_hours=24)
    talent_store.set_offer_status(oid, OfferStatus.ACCEPTED)

    items = build_talent_brief_items()
    assert items[0].offers_expiring_soon == 0
    assert "expiring" not in format_talent_for_prompt()


def test_expiring_offers_sort_first(db: Path) -> None:
    # Engagement A: big pipeline, no expiring offer. Engagement B: one
    # expiring offer. B must sort first — it's the most time-critical.
    eid_a = talent_store.upsert_engagement(role_title="VP Sales")
    for n in range(5):
        talent_store.upsert_candidate(
            engagement_id=eid_a, full_name=f"Lead {n}", stage=CandidateStage.LEAD
        )
    eid_b = talent_store.upsert_engagement(role_title="CFO")
    cid_b = talent_store.upsert_candidate(
        engagement_id=eid_b, full_name="Closer", stage=CandidateStage.OFFER
    )
    _seed_extended_offer(eid_b, cid_b, expires_in_hours=24)

    items = build_talent_brief_items()
    assert items[0].engagement_id == eid_b
