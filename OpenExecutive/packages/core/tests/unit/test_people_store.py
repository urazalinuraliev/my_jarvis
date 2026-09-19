"""Store-level tests for the People feature."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openexecutive.people import store as people_store
from openexecutive.people.models import AuthorityScope, AvailabilityWindow


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "people.db"
    monkeypatch.setattr(people_store, "DB_PATH", path)
    people_store.initialize_db()
    return path


def test_initialize_db_idempotent(db: Path) -> None:
    people_store.initialize_db()
    people_store.initialize_db()
    assert people_store.list_people() == []


def test_upsert_insert_returns_id(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Alex Rivera", role="CEO", is_principal=True)
    assert pid > 0
    p = people_store.get_person(pid)
    assert p is not None
    assert p.full_name == "Alex Rivera"
    assert p.role == "CEO"
    assert p.is_principal is True
    assert p.archived is False


def test_upsert_update_existing(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Alex", role="CEO")
    people_store.upsert_person(full_name="Alex Rivera", role="Founder & CEO", person_id=pid)
    p = people_store.get_person(pid)
    assert p is not None
    assert p.full_name == "Alex Rivera"
    assert p.role == "Founder & CEO"


def test_list_people_excludes_archived_by_default(db: Path) -> None:
    pid1 = people_store.upsert_person(full_name="Active Person", role="CTO")
    pid2 = people_store.upsert_person(full_name="Archived Person", role="Ex-CFO")
    people_store.archive_person(pid2)

    active = people_store.list_people()
    assert len(active) == 1
    assert active[0].id == pid1

    all_people = people_store.list_people(include_archived=True)
    assert len(all_people) == 2


def test_archive_person_sets_flag(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Jamie Park")
    assert people_store.archive_person(pid) is True
    p = people_store.get_person(pid)
    assert p is not None
    assert p.archived is True


def test_archive_person_returns_false_for_unknown(db: Path) -> None:
    assert people_store.archive_person(9999) is False


def test_authority_scope_round_trip(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Sarah Chen", role="CFO (fractional)")
    people_store.set_authority_scope(
        pid, [AuthorityScope.SPEND_GT_10K, AuthorityScope.BOARD_COMMS]
    )
    p = people_store.get_person(pid)
    assert p is not None
    assert set(p.authority_scope) == {AuthorityScope.SPEND_GT_10K, AuthorityScope.BOARD_COMMS}


def test_set_authority_scope_replaces_existing(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Sarah Chen")
    people_store.set_authority_scope(pid, [AuthorityScope.SPEND_GT_10K])
    people_store.set_authority_scope(pid, [AuthorityScope.LEGAL_SIGN])
    p = people_store.get_person(pid)
    assert p is not None
    assert p.authority_scope == [AuthorityScope.LEGAL_SIGN]


def test_availability_round_trip(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Sarah Chen")
    win = AvailabilityWindow(
        weekdays=[1],  # Tuesday
        start_local="09:00",
        end_local="13:00",
        timezone="America/Los_Angeles",
    )
    people_store.set_availability(pid, [win])
    p = people_store.get_person(pid)
    assert p is not None
    assert len(p.availability) == 1
    assert p.availability[0].weekdays == [1]
    assert p.availability[0].start_local == "09:00"
    assert p.availability[0].timezone == "America/Los_Angeles"


def test_on_leave_stored_and_retrieved(db: Path) -> None:
    pid = people_store.upsert_person(
        full_name="Devon Liu",
        on_leave_until=date(2026, 8, 1),
    )
    p = people_store.get_person(pid)
    assert p is not None
    assert p.on_leave_until == date(2026, 8, 1)


def test_update_person_partial(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Alex", role="CEO")
    people_store.update_person(pid, role="Founder & CEO", email="alex@example.com")
    p = people_store.get_person(pid)
    assert p is not None
    assert p.role == "Founder & CEO"
    assert p.email == "alex@example.com"
    assert p.full_name == "Alex"  # unchanged


def test_update_person_clear_on_leave(db: Path) -> None:
    pid = people_store.upsert_person(
        full_name="Alex", on_leave_until=date(2026, 8, 1)
    )
    people_store.update_person(pid, clear_on_leave=True)
    p = people_store.get_person(pid)
    assert p is not None
    assert p.on_leave_until is None


# --------------------------------------------------------------------------- #
# find_approvers
# --------------------------------------------------------------------------- #

def test_find_approvers_returns_matching_scope(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Sarah Chen", role="CFO")
    people_store.set_authority_scope(pid, [AuthorityScope.SPEND_GT_10K])

    approvers = people_store.find_approvers(AuthorityScope.SPEND_GT_10K)
    assert len(approvers) == 1
    assert approvers[0].full_name == "Sarah Chen"


def test_find_approvers_wildcard_matches_any_token(db: Path) -> None:
    principal_id = people_store.upsert_person(
        full_name="Alex Rivera", role="CEO", is_principal=True
    )
    people_store.set_authority_scope(principal_id, [AuthorityScope.WILDCARD])

    approvers = people_store.find_approvers(AuthorityScope.LEGAL_SIGN)
    assert any(a.id == principal_id for a in approvers)


def test_find_approvers_excludes_archived(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Ex-CFO")
    people_store.set_authority_scope(pid, [AuthorityScope.SPEND_GT_10K])
    people_store.archive_person(pid)

    approvers = people_store.find_approvers(AuthorityScope.SPEND_GT_10K)
    assert not any(a.id == pid for a in approvers)


def test_find_approvers_non_principal_sorts_before_principal(db: Path) -> None:
    """Humans (non-principals) should appear before the fallback principal."""
    principal_id = people_store.upsert_person(
        full_name="Founder", role="CEO", is_principal=True
    )
    people_store.set_authority_scope(principal_id, [AuthorityScope.WILDCARD])

    cfo_id = people_store.upsert_person(
        full_name="Sarah CFO", role="CFO", is_principal=False, response_sla_hours=4
    )
    people_store.set_authority_scope(cfo_id, [AuthorityScope.SPEND_GT_10K])

    approvers = people_store.find_approvers(AuthorityScope.SPEND_GT_10K)
    assert len(approvers) == 2
    # Non-principal (Sarah) must be first.
    assert approvers[0].is_principal is False
    assert approvers[0].full_name == "Sarah CFO"
    assert approvers[1].is_principal is True


def test_find_approvers_sla_sort_within_non_principals(db: Path) -> None:
    """Among non-principals, lower SLA should come first."""
    pid_slow = people_store.upsert_person(
        full_name="Slow Approver", response_sla_hours=48
    )
    pid_fast = people_store.upsert_person(
        full_name="Fast Approver", response_sla_hours=4
    )
    people_store.set_authority_scope(pid_slow, [AuthorityScope.HIRING_SIGNOFF])
    people_store.set_authority_scope(pid_fast, [AuthorityScope.HIRING_SIGNOFF])

    approvers = people_store.find_approvers(AuthorityScope.HIRING_SIGNOFF)
    assert approvers[0].full_name == "Fast Approver"
    assert approvers[1].full_name == "Slow Approver"


def test_find_approvers_returns_empty_when_none(db: Path) -> None:
    people_store.upsert_person(full_name="No Scope Person")
    approvers = people_store.find_approvers(AuthorityScope.LEGAL_SIGN)
    assert approvers == []


def test_get_person_returns_none_for_unknown(db: Path) -> None:
    assert people_store.get_person(9999) is None


def test_upsert_person_id_zero_inserts_not_updates(db: Path) -> None:
    """person_id=0 should not silently no-op as an UPDATE; it should insert."""
    pid = people_store.upsert_person(full_name="Real Person")
    # id=0 is treated as None (no valid row with id=0 in AUTOINCREMENT tables).
    pid2 = people_store.upsert_person(full_name="Another", person_id=0)
    # Should insert a new row, not silently fail.
    assert pid2 > 0
    assert pid2 != pid


def test_list_people_principal_first(db: Path) -> None:
    """Principal row should be returned before regular staff."""
    people_store.upsert_person(full_name="Staff A", is_principal=False)
    people_store.upsert_person(full_name="The Principal", is_principal=True)
    people_store.upsert_person(full_name="Staff B", is_principal=False)

    people = people_store.list_people()
    assert people[0].is_principal is True


def test_find_principal_returns_principal_row(db: Path) -> None:
    people_store.upsert_person(full_name="Staff", is_principal=False)
    pid = people_store.upsert_person(full_name="The Boss", is_principal=True)
    found = people_store.find_principal_person()
    assert found is not None
    assert found.id == pid


def test_find_principal_returns_none_when_absent(db: Path) -> None:
    people_store.upsert_person(full_name="Staff", is_principal=False)
    assert people_store.find_principal_person() is None


def test_find_principal_skips_archived(db: Path) -> None:
    pid = people_store.upsert_person(full_name="Ex Boss", is_principal=True)
    people_store.archive_person(pid)
    assert people_store.find_principal_person() is None


def test_find_principal_no_db_file_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Before initialize_db() runs, the helper must not crash."""
    missing = tmp_path / "never_created.db"
    monkeypatch.setattr(people_store, "DB_PATH", missing)
    assert people_store.find_principal_person() is None


def test_find_person_by_email_returns_none_when_table_missing(tmp_path: Path) -> None:
    # Shared episodic DB file exists (created by a sibling subsystem) but the
    # people table was never initialized — email intake must treat this as an
    # unknown sender, not raise OperationalError.
    import sqlite3
    shared = tmp_path / "shared.db"
    conn = sqlite3.connect(str(shared))
    conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    assert people_store.find_person_by_email("a@b.com", db_path=shared) is None
