"""Tests for the offers table in the talent store (close-the-hire-loop)."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.talent import store as talent_store
from openexecutive.talent.models import (
    TERMINAL_OFFER_STATUSES,
    OfferStatus,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _seed_candidate(role_title: str = "VP Drilling") -> int:
    eid = talent_store.upsert_engagement(role_title=role_title)
    return talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")


def _make_offer(candidate_id: int, **kwargs) -> int:
    cand = talent_store.get_candidate(candidate_id)
    assert cand is not None
    return talent_store.create_offer(
        candidate_id=candidate_id,
        engagement_id=cand.engagement_id,
        comp_summary="base 300k, 0.5% equity",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Create / read
# --------------------------------------------------------------------------- #

def test_create_and_get_offer(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid, note="strong finalist")

    offer = talent_store.get_offer(oid)
    assert offer is not None
    assert offer.candidate_id == cid
    assert offer.status is OfferStatus.DRAFT
    assert offer.comp_summary == "base 300k, 0.5% equity"
    assert offer.note == "strong finalist"
    assert offer.created_at and offer.updated_at
    assert offer.expires_at is None
    assert offer.nudge_action_ids == []


def test_one_open_offer_per_candidate(db: Path) -> None:
    cid = _seed_candidate()
    _make_offer(cid)
    with pytest.raises(ValueError, match="already has an open offer"):
        _make_offer(cid)


def test_terminal_offer_frees_the_slot(db: Path) -> None:
    cid = _seed_candidate()
    first = _make_offer(cid)
    talent_store.set_offer_status(first, OfferStatus.EXTENDED)
    talent_store.set_offer_status(first, OfferStatus.DECLINED)
    # A decided offer is history — a new one can be created.
    second = _make_offer(cid)
    assert second != first
    assert talent_store.get_open_offer_for_candidate(cid).id == second  # type: ignore[union-attr]


def test_create_rejects_non_insert_statuses(db: Path) -> None:
    cid = _seed_candidate()
    with pytest.raises(ValueError, match="draft/pending_approval"):
        _make_offer(cid, status=OfferStatus.EXTENDED)


def test_get_open_offer_ignores_archived(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)
    assert talent_store.get_open_offer_for_candidate(cid) is not None
    talent_store.archive_offer(oid)
    assert talent_store.get_open_offer_for_candidate(cid) is None


def test_list_offers_filters(db: Path) -> None:
    cid_a = _seed_candidate("VP Drilling")
    cid_b = _seed_candidate("CFO")
    oid_a = _make_offer(cid_a)
    _make_offer(cid_b)

    assert len(talent_store.list_offers()) == 2
    assert [o.id for o in talent_store.list_offers(candidate_id=cid_a)] == [oid_a]
    talent_store.set_offer_status(oid_a, OfferStatus.EXTENDED)
    extended = talent_store.list_offers(status=OfferStatus.EXTENDED)
    assert [o.id for o in extended] == [oid_a]

    cand_b = talent_store.get_candidate(cid_b)
    assert cand_b is not None
    by_eng = talent_store.list_offers(engagement_id=cand_b.engagement_id)
    assert len(by_eng) == 1


# --------------------------------------------------------------------------- #
# Transition matrix
# --------------------------------------------------------------------------- #

def test_legal_forward_path_stamps_timestamps(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)

    assert talent_store.set_offer_status(oid, OfferStatus.PENDING_APPROVAL)
    assert talent_store.set_offer_status(
        oid, OfferStatus.EXTENDED, expires_at="2030-01-01T00:00:00+00:00",
        nudge_action_ids=[11, 12],
    )
    offer = talent_store.get_offer(oid)
    assert offer is not None
    assert offer.extended_at != ""
    assert offer.expires_at == "2030-01-01T00:00:00+00:00"
    assert offer.nudge_action_ids == [11, 12]
    assert offer.decided_at == ""

    assert talent_store.set_offer_status(oid, OfferStatus.ACCEPTED)
    offer = talent_store.get_offer(oid)
    assert offer is not None
    assert offer.decided_at != ""


def test_pending_can_fall_back_to_draft(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)
    talent_store.set_offer_status(oid, OfferStatus.PENDING_APPROVAL)
    assert talent_store.set_offer_status(oid, OfferStatus.DRAFT)


@pytest.mark.parametrize("bad_target", [
    OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED,
])
def test_draft_cannot_jump_to_terminal_decisions(db: Path, bad_target: OfferStatus) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)
    assert not talent_store.set_offer_status(oid, bad_target)
    offer = talent_store.get_offer(oid)
    assert offer is not None and offer.status is OfferStatus.DRAFT


def test_rescind_works_from_every_open_status(db: Path) -> None:
    for setup in (
        [],
        [OfferStatus.PENDING_APPROVAL],
        [OfferStatus.PENDING_APPROVAL, OfferStatus.EXTENDED],
    ):
        cid = _seed_candidate()
        oid = _make_offer(cid)
        for step in setup:
            assert talent_store.set_offer_status(oid, step)
        assert talent_store.set_offer_status(oid, OfferStatus.RESCINDED)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_OFFER_STATUSES))
def test_terminal_statuses_are_immutable(db: Path, terminal: OfferStatus) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)
    talent_store.set_offer_status(oid, OfferStatus.EXTENDED)
    assert talent_store.set_offer_status(oid, terminal)
    for target in OfferStatus:
        assert not talent_store.set_offer_status(oid, target), (
            f"{terminal.value} -> {target.value} should be illegal"
        )


def test_set_status_unknown_or_archived_offer(db: Path) -> None:
    assert not talent_store.set_offer_status(999, OfferStatus.EXTENDED)
    cid = _seed_candidate()
    oid = _make_offer(cid)
    talent_store.archive_offer(oid)
    assert not talent_store.set_offer_status(oid, OfferStatus.EXTENDED)


# --------------------------------------------------------------------------- #
# Terms editing
# --------------------------------------------------------------------------- #

def test_update_terms_only_pre_extension(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)

    assert talent_store.update_offer_terms(oid, comp_summary="base 320k", package_md="# Pkg")
    offer = talent_store.get_offer(oid)
    assert offer is not None
    assert offer.comp_summary == "base 320k"
    assert offer.package_md == "# Pkg"

    talent_store.set_offer_status(oid, OfferStatus.EXTENDED)
    assert not talent_store.update_offer_terms(oid, comp_summary="base 999k")
    offer = talent_store.get_offer(oid)
    assert offer is not None and offer.comp_summary == "base 320k"


def test_update_terms_with_no_fields_is_noop(db: Path) -> None:
    cid = _seed_candidate()
    oid = _make_offer(cid)
    assert not talent_store.update_offer_terms(oid)


def test_db_level_backstop_blocks_concurrent_second_open_offer(db: Path) -> None:
    """The partial unique index catches a create that races past the SELECT guard."""
    import sqlite3

    cid = _seed_candidate()
    _make_offer(cid)
    # Bypass create_offer's SELECT guard to simulate the losing racer's INSERT.
    with pytest.raises(sqlite3.IntegrityError), talent_store._get_conn() as conn:
        conn.execute(
            "INSERT INTO offers (candidate_id, engagement_id, status, comp_summary,"
            " package_md, note, created_at, updated_at)"
            " VALUES (?, ?, 'draft', '', '', '', '2026-01-01', '2026-01-01')",
            (cid, talent_store.get_candidate(cid).engagement_id),  # type: ignore[union-attr]
            )
