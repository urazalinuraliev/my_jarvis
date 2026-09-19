"""Tests for the shared talent reminder helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.people.models import Person
from openexecutive.talent import reminders as reminders_mod
from openexecutive.talent import store as talent_store
from openexecutive.talent.reminders import (
    ReminderContext,
    company_name,
    principal_channel,
    resolve_reminder_context,
    schedule_reminder,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "shared.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    monkeypatch.setattr(people_store, "DB_PATH", path)
    monkeypatch.setattr(episodic, "DB_PATH", path)
    episodic.initialize_db(path)
    people_store.initialize_db(path)
    talent_store.initialize_db(path)
    return path


def _seed_candidate() -> int:
    eid = talent_store.upsert_engagement(role_title="VP Drilling", department="Drilling")
    return talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")


# --------------------------------------------------------------------------- #
# company_name
# --------------------------------------------------------------------------- #

def test_company_name_uses_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from openexecutive.onboarding import profile_builder

    class _Profile:
        name = "Acme Energy"

    monkeypatch.setattr(profile_builder, "load_or_create_profile", lambda: _Profile())
    assert company_name() == "Acme Energy"


def test_company_name_falls_back_when_unnamed(monkeypatch: pytest.MonkeyPatch) -> None:
    from openexecutive.onboarding import profile_builder

    class _Profile:
        name = ""

    monkeypatch.setattr(profile_builder, "load_or_create_profile", lambda: _Profile())
    assert company_name() == "the company"


# --------------------------------------------------------------------------- #
# principal_channel
# --------------------------------------------------------------------------- #

def test_principal_channel_resolution() -> None:
    assert principal_channel(
        Person(full_name="A", email="a@x.com", preferred_channel="email")
    ) == ("email", "a@x.com")
    # slack → slack_dm
    assert principal_channel(
        Person(full_name="A", slack_user_id="U123", preferred_channel="slack")
    ) == ("slack_dm", "U123")
    # "any" → priority order (email first)
    assert principal_channel(
        Person(full_name="A", email="a@x.com", slack_user_id="U1", preferred_channel="any")
    ) == ("email", "a@x.com")
    # preferred channel without its ref → fall back
    assert principal_channel(
        Person(full_name="A", slack_user_id="U1", preferred_channel="telegram")
    ) == ("slack_dm", "U1")
    # no usable channel
    assert principal_channel(Person(full_name="A", preferred_channel="any")) is None


# --------------------------------------------------------------------------- #
# resolve_reminder_context
# --------------------------------------------------------------------------- #

def test_resolve_context_success(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cand_id = _seed_candidate()
    people_store.upsert_person(
        full_name="Alex", is_principal=True, email="boss@x.com", preferred_channel="email"
    )
    # In-house model: the reminder context carries the COMPANY name (from the
    # profile), not an external client. Control the profile so the assertion is
    # deterministic.
    from openexecutive.onboarding import profile_builder

    class _Profile:
        name = "Meridian Petroleum"

    monkeypatch.setattr(profile_builder, "load_or_create_profile", lambda: _Profile())

    ctx = resolve_reminder_context(cand_id)
    assert isinstance(ctx, ReminderContext)
    assert ctx.candidate.id == cand_id
    assert ctx.engagement.role_title == "VP Drilling"
    assert ctx.company_name == "Meridian Petroleum"
    assert ctx.channel == "email"
    assert ctx.channel_ref == "boss@x.com"


def test_resolve_context_unknown_candidate(db: Path) -> None:
    assert resolve_reminder_context(9999) == "Candidate 9999 not found."


def test_resolve_context_no_principal(db: Path) -> None:
    cand_id = _seed_candidate()
    assert resolve_reminder_context(cand_id) == "No principal configured to receive reminders."


def test_resolve_context_principal_without_channel(db: Path) -> None:
    cand_id = _seed_candidate()
    people_store.upsert_person(full_name="Alex", is_principal=True, preferred_channel="any")
    msg = resolve_reminder_context(cand_id)
    assert isinstance(msg, str)
    assert "no reachable channel" in msg


# --------------------------------------------------------------------------- #
# schedule_reminder
# --------------------------------------------------------------------------- #

def test_schedule_reminder_targets_principal(db: Path) -> None:
    from datetime import UTC, datetime

    cand_id = _seed_candidate()
    pid = people_store.upsert_person(
        full_name="Alex", is_principal=True, email="boss@x.com", preferred_channel="email"
    )
    ctx = resolve_reminder_context(cand_id)
    assert isinstance(ctx, ReminderContext)
    aid = schedule_reminder(ctx=ctx, run_at=datetime.now(UTC), intent_text="ping")
    assert aid > 0
    actions = episodic.list_scheduled_actions()
    assert len(actions) == 1
    assert actions[0].assigned_to_person_id == pid
    assert actions[0].channel == "email"
    assert actions[0].channel_ref == "boss@x.com"
    assert actions[0].intent_text == "ping"


def test_channel_map_only_emits_valid_scheduled_channels() -> None:
    # Every mapped scheduled channel must be accepted by insert_scheduled_action.
    from openexecutive.memory.episodic import _VALID_SCHEDULED_CHANNELS

    for sched in reminders_mod._PEOPLE_TO_SCHEDULED_CHANNEL.values():
        assert sched in _VALID_SCHEDULED_CHANNELS
