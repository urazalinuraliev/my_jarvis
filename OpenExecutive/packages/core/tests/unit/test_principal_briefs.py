"""Tests for the morning_brief / end_of_day_digest workflows and the
scheduler-side seeding + chain-next plumbing.

The workflow LLM calls are stubbed — we verify the registration,
input model shape, scheduler seeding idempotency, time-of-day parsing,
and the chain-on-fire behaviour. Actual LLM-rendered content is out
of scope for unit tests.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openexecutive.memory import episodic
from openexecutive.scheduler import runner
from openexecutive.workflows import WORKFLOW_REGISTRY


def _setup_isolated_db(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(episodic, "DB_PATH", db)
    episodic.initialize_db(db)


# ---------------------------------------------------------------------------
# Workflow registration
# ---------------------------------------------------------------------------

def test_morning_brief_registered() -> None:
    assert "morning_brief" in WORKFLOW_REGISTRY
    wf = WORKFLOW_REGISTRY["morning_brief"]
    assert wf.title
    assert wf.description
    assert len(wf.steps()) >= 1
    meta = wf.meta()
    # Input model has at least the period_label field, all optional.
    assert "period_label" in meta.input_schema.get("properties", {})


def test_end_of_day_digest_registered() -> None:
    assert "end_of_day_digest" in WORKFLOW_REGISTRY
    wf = WORKFLOW_REGISTRY["end_of_day_digest"]
    assert wf.title
    meta = wf.meta()
    assert "period_label" in meta.input_schema.get("properties", {})


# ---------------------------------------------------------------------------
# Time-of-day parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08:00", (8, 0)),
        ("18:30", (18, 30)),
        ("00:00", (0, 0)),
        ("23:59", (23, 59)),
        ("", (8, 0)),  # falls back to default
        ("not-a-time", (8, 0)),
        ("25:00", (8, 0)),  # out of range
        ("12:60", (8, 0)),  # minutes out of range
    ],
)
def test_parse_hhmm(raw: str, expected: tuple[int, int]) -> None:
    assert runner._parse_hhmm(raw, "08:00") == expected


def test_next_occurrence_picks_today_when_target_is_later() -> None:
    base = datetime(2026, 5, 26, 7, 0, tzinfo=UTC)
    result = runner._next_occurrence(base, 8, 0)
    assert result == datetime(2026, 5, 26, 8, 0, tzinfo=UTC)


def test_next_occurrence_advances_to_tomorrow_when_target_passed() -> None:
    base = datetime(2026, 5, 26, 9, 0, tzinfo=UTC)
    result = runner._next_occurrence(base, 8, 0)
    assert result == datetime(2026, 5, 27, 8, 0, tzinfo=UTC)


def test_next_occurrence_advances_when_equal_to_now() -> None:
    """Exactly at target time should advance to tomorrow — strictly future."""
    base = datetime(2026, 5, 26, 8, 0, tzinfo=UTC)
    result = runner._next_occurrence(base, 8, 0)
    assert result == datetime(2026, 5, 27, 8, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Scheduler seeding idempotency
# ---------------------------------------------------------------------------

def test_seed_principal_briefs_inserts_all_recurring_rows_on_fresh_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shift 5 added `executive_reflection` to the seed loop alongside
    the morning and EoD brief. Fresh DB → 3 rows."""
    _setup_isolated_db(tmp_path / "briefs.db", monkeypatch)

    inserted = runner.seed_principal_briefs()
    assert inserted == 3

    actions = episodic.list_scheduled_actions(status="pending", limit=10)
    kinds = {a.kind for a in actions}
    assert "principal_brief_morning" in kinds
    assert "principal_brief_eod" in kinds
    assert "executive_reflection" in kinds


def test_seed_principal_briefs_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_isolated_db(tmp_path / "briefs2.db", monkeypatch)
    runner.seed_principal_briefs()

    # Second call must not duplicate.
    inserted = runner.seed_principal_briefs()
    assert inserted == 0
    pending = [
        a for a in episodic.list_scheduled_actions(status="pending", limit=10)
        if a.kind in (
            "principal_brief_morning",
            "principal_brief_eod",
            "executive_reflection",
        )
    ]
    # Shift 5 added executive_reflection; the idempotency contract now
    # covers all three.
    assert len(pending) == 3


def test_seed_uses_env_var_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PRINCIPAL_BRIEF_MORNING_TIME is set, the seeded row uses that
    HH:MM rather than the 08:00 default."""
    _setup_isolated_db(tmp_path / "briefs3.db", monkeypatch)
    monkeypatch.setenv("PRINCIPAL_BRIEF_MORNING_TIME", "06:30")
    monkeypatch.setenv("PRINCIPAL_BRIEF_EOD_TIME", "17:15")

    runner.seed_principal_briefs()
    actions = {
        a.kind: a for a in episodic.list_scheduled_actions(status="pending", limit=10)
    }
    morning = actions["principal_brief_morning"]
    eod = actions["principal_brief_eod"]
    # Parse run_at and check HH:MM matches the env vars.
    morning_dt = datetime.fromisoformat(morning.run_at)
    eod_dt = datetime.fromisoformat(eod.run_at)
    assert (morning_dt.hour, morning_dt.minute) == (6, 30)
    assert (eod_dt.hour, eod_dt.minute) == (17, 15)


# ---------------------------------------------------------------------------
# Chain-next on fire
# ---------------------------------------------------------------------------

def test_enqueue_next_principal_brief_advances_24h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a brief fires at noon, the next occurrence must be tomorrow at
    the configured time-of-day — not 24h literal from now."""
    _setup_isolated_db(tmp_path / "briefs4.db", monkeypatch)
    monkeypatch.setenv("PRINCIPAL_BRIEF_MORNING_TIME", "08:00")

    # Fire-time is "after" — well past today's 08:00.
    after = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    aid = runner._enqueue_next_principal_brief("principal_brief_morning", after=after)
    assert aid is not None

    row = episodic.get_scheduled_action(aid)
    assert row is not None
    next_dt = datetime.fromisoformat(row.run_at)
    # Strictly after the fire-time AND at 08:00 UTC.
    assert next_dt > after
    assert next_dt.hour == 8 and next_dt.minute == 0


def test_has_pending_brief_detects_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_isolated_db(tmp_path / "briefs5.db", monkeypatch)
    assert runner._has_pending_brief("principal_brief_morning") is False
    runner.seed_principal_briefs()
    assert runner._has_pending_brief("principal_brief_morning") is True
    assert runner._has_pending_brief("principal_brief_eod") is True
