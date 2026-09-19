"""Engagement value report: gatherer scoping + workflow assembly.

The report's whole claim is "generated from the engagement's own record" —
so these tests prove the gatherer's period scoping is exact, that the
artifact lists only gathered facts (the LLM step is mocked), and that the
parked-slot path reads a real slot's state.db without activation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openexecutive.clients import slots
from openexecutive.clients.engagement_activity import gather_engagement_activity
from openexecutive.clients.slots import activate_client_slot, create_client_slot
from openexecutive.workflows import WORKFLOW_REGISTRY
from openexecutive.workflows import engagement_value_report as evr
from openexecutive.workflows.engagement_value_report import (
    EngagementValueReportInput,
    EngagementValueReportWorkflow,
)


def _make_db(tmp_path: Path) -> Path:
    from openexecutive.memory import episodic
    from openexecutive.workflows import persistence

    db = tmp_path / "episodic.db"
    episodic.initialize_db(db)
    persistence.initialize_runs_db(db)
    return db


def _seed_activity(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        # Two decisions in period, one before it.
        for ts, summary in (
            ("2026-04-10T09:00:00", "Standardized inverter vendor"),
            ("2026-05-20T09:00:00", "Approved Q3 pricing change"),
            ("2026-01-05T09:00:00", "Ancient decision (out of range)"),
        ):
            conn.execute(
                "INSERT INTO decisions (timestamp, domain, summary, rationale, "
                "outcome, tags, department) VALUES (?, 'operations', ?, '', "
                "'adopted', '', '')",
                (ts, summary),
            )
        conn.execute(
            "INSERT INTO initiatives (title, status, created_at, updated_at, "
            "summary, department) VALUES ('Margin program', 'active', "
            "'2026-04-01T00:00:00', '2026-05-01T00:00:00', 'Visibility work', '')"
        )
        conn.execute(
            "INSERT INTO advice_given (timestamp, domain, query_summary, "
            "advice_summary, department) VALUES ('2026-05-02T10:00:00', "
            "'finance', 'q', 'a', '')"
        )
        # A delivered workflow artifact in range, plus a value report that
        # must be excluded (the report never lists itself).
        conn.execute(
            "INSERT INTO workflow_runs (run_id, workflow_name, title, status, "
            "inputs, artifact, created_at, updated_at) VALUES "
            "('r1', 'board_prep', 'Board prep — May', 'done', '{}', '# deck', "
            "'2026-05-15T08:00:00', '2026-05-15T08:30:00')"
        )
        conn.execute(
            "INSERT INTO workflow_runs (run_id, workflow_name, title, status, "
            "inputs, artifact, created_at, updated_at) VALUES "
            "('r2', 'engagement_value_report', 'Prior value report', 'done', "
            "'{}', '# old report', '2026-05-16T08:00:00', '2026-05-16T08:30:00')"
        )
        # Follow-ups: one done in range, one pending.
        conn.execute(
            "INSERT INTO scheduled_actions (created_at, run_at, channel, "
            "channel_ref, intent_text, status, attempts, last_error, "
            "department, kind) VALUES ('2026-05-01T00:00:00', "
            "'2026-05-03T00:00:00', 'any', '', 'nudge vendor', 'done', 0, '', "
            "'', 'ad_hoc')"
        )
        conn.execute(
            "INSERT INTO scheduled_actions (created_at, run_at, channel, "
            "channel_ref, intent_text, status, attempts, last_error, "
            "department, kind) VALUES ('2026-05-01T00:00:00', "
            "'2099-01-01T00:00:00', 'any', '', 'future nudge', 'pending', 0, "
            "'', '', 'ad_hoc')"
        )
        conn.commit()
    finally:
        conn.close()


def test_gatherer_scopes_to_period_and_excludes_self(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    _seed_activity(db)

    activity = gather_engagement_activity(db, "2026-03-01", "2026-06-01T23:59:59")

    assert [d.summary for d in activity.decisions] == [
        "Approved Q3 pricing change",
        "Standardized inverter vendor",
    ]
    assert [i.title for i in activity.initiatives] == ["Margin program"]
    assert activity.advice_count == 1
    assert activity.advice_by_domain == {"finance": 1}
    # Self-exclusion: only board_prep listed, not the prior value report.
    assert [w.workflow_name for w in activity.deliverables] == ["board_prep"]
    assert activity.followups_completed == 1
    assert activity.followups_pending == 1
    assert activity.is_empty() is False


def test_gatherer_degrades_on_missing_tables_and_missing_db(tmp_path: Path) -> None:
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()  # empty DB, zero tables
    activity = gather_engagement_activity(bare, "2026-01-01", "2026-12-31")
    assert activity.is_empty() is True

    missing = gather_engagement_activity(
        tmp_path / "nope.db", "2026-01-01", "2026-12-31"
    )
    assert missing.is_empty() is True


def test_workflow_registered_with_schema() -> None:
    wf = WORKFLOW_REGISTRY["engagement_value_report"]
    assert isinstance(wf, EngagementValueReportWorkflow)
    meta = wf.meta()
    field_names = set(meta.input_schema["properties"])
    assert {"client_slug", "period_start", "period_end", "audience_note"} <= field_names
    assert [s.id for s in wf.steps()] == ["context", "gather", "narrative", "assemble"]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Client-slot environment (pattern from test_client_slots.py)."""
    company = tmp_path / "company"
    company.mkdir()
    settings = SimpleNamespace(
        company_profile_path=company / "profile.yaml",
        vector_store_path=tmp_path / "chroma",
        mcp_servers_config_path=company / "mcp_servers.json",
        honcho_workspace_id="default-ws",
    )
    settings.company_profile_path.write_text("name: Meridian Solar\n")

    from openexecutive import config
    from openexecutive.memory import episodic
    from openexecutive.workflows import persistence

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)
    persistence.initialize_runs_db(db_path)
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    async def _no_vector(_settings: Any, _app_state: Any) -> int:
        return 0

    monkeypatch.setattr(slots, "_rebuild_vector_state", _no_vector)
    monkeypatch.setattr(slots, "_set_honcho_client_workspace", lambda _slug: None)
    monkeypatch.setattr(slots, "_reseed_blank_defaults", lambda **kw: None)
    monkeypatch.setattr(slots, "snapshot_user_state", lambda _s: None)
    return SimpleNamespace(settings=settings, db_path=db_path, company=company)


async def _run_workflow(inputs: EngagementValueReportInput) -> tuple[str, list[Any]]:
    wf = EngagementValueReportWorkflow()
    events: list[Any] = []
    artifact = ""
    async for event in wf.run(inputs, store=None):  # type: ignore[arg-type]
        events.append(event)
        if event.type == "artifact" and event.content:
            artifact = event.content
    return artifact, events


async def test_workflow_artifact_for_active_client(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(env.db_path)
    await create_client_slot(env.settings, display_name="Meridian Solar", source="current")
    await slots.update_client_meta(
        env.settings,
        "meridian_solar",
        {"role": "Fractional COO", "renewal_date": "2026-07-01"},
    )

    captured: dict[str, str] = {}

    async def _fake_specialist(*, specialist_name: str, query: str, **kw: Any) -> str:
        captured["specialist"] = specialist_name
        captured["query"] = query
        return "A productive period across operations and pricing."

    monkeypatch.setattr(evr, "route_to_specialist", _fake_specialist)

    artifact, events = await _run_workflow(
        EngagementValueReportInput(period_start="2026-03-01", period_end="2026-06-01")
    )

    assert captured["specialist"] == "board_comms"
    # Facts are serialized into the narrative prompt — grounding contract.
    assert "Approved Q3 pricing change" in captured["query"]

    assert "# Engagement Value Report — Meridian Solar" in artifact
    assert "Fractional COO" in artifact
    assert "Period: 2026-03-01 – 2026-06-01" in artifact
    assert "Standardized inverter vendor" in artifact
    assert "Ancient decision" not in artifact  # period scoping in the artifact
    assert "Board prep — May" in artifact
    assert "Prior value report" not in artifact  # self-exclusion
    assert "1 follow-ups completed" in artifact
    assert "Engagement renewal/review: 2026-07-01" in artifact
    assert not [e for e in events if e.type == "error"]


async def test_workflow_reads_parked_slot_without_activation(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(env.db_path)
    await create_client_slot(env.settings, display_name="Meridian Solar", source="current")
    await create_client_slot(env.settings, display_name="Beta", source="blank")
    await activate_client_slot(env.settings, "beta")  # parks Meridian

    async def _fake_specialist(**kw: Any) -> str:
        return "Summary."

    monkeypatch.setattr(evr, "route_to_specialist", _fake_specialist)

    artifact, events = await _run_workflow(
        EngagementValueReportInput(
            client_slug="meridian_solar",
            period_start="2026-03-01",
            period_end="2026-06-01",
        )
    )

    # Parked data came from the slot's state.db; Beta stayed active.
    assert slots.get_active_client(env.settings) == "beta"
    assert "Meridian Solar" in artifact
    assert "Approved Q3 pricing change" in artifact
    ctx_done = next(e for e in events if e.type == "step_done" and e.step_id == "context")
    assert "parked slot" in (ctx_done.summary or "")


async def test_workflow_errors_cleanly_on_unknown_or_never_activated(
    env: SimpleNamespace,
) -> None:
    _, events = await _run_workflow(
        EngagementValueReportInput(client_slug="nope")
    )
    assert any(e.type == "error" for e in events)

    await create_client_slot(env.settings, display_name="Fresh", source="blank")
    _, events = await _run_workflow(
        EngagementValueReportInput(client_slug="fresh")
    )
    errs = [e for e in events if e.type == "error"]
    assert errs and "never been activated" in errs[0].message


async def test_workflow_empty_period_skips_llm(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No recorded activity → honest empty narrative, no specialist call."""
    calls: list[str] = []

    async def _fake_specialist(**kw: Any) -> str:
        calls.append("called")
        return "x"

    monkeypatch.setattr(evr, "route_to_specialist", _fake_specialist)

    artifact, events = await _run_workflow(
        EngagementValueReportInput(period_start="2030-01-01", period_end="2030-02-01")
    )
    assert calls == []
    assert "No recorded activity in this period" in artifact
    assert not [e for e in events if e.type == "error"]


async def test_pending_only_period_is_coherent(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only pending follow-ups (point-in-time) → empty-period narrative, and
    the pending count appears under Looking ahead, never as period activity."""
    conn = sqlite3.connect(str(env.db_path))
    conn.execute(
        "INSERT INTO scheduled_actions (created_at, run_at, channel, "
        "channel_ref, intent_text, status, attempts, last_error, department, "
        "kind) VALUES ('2026-05-01T00:00:00', '2099-01-01T00:00:00', 'any', "
        "'', 'future nudge', 'pending', 0, '', '', 'ad_hoc')"
    )
    conn.commit()
    conn.close()

    calls: list[str] = []

    async def _fake_specialist(**kw: Any) -> str:
        calls.append("called")
        return "x"

    monkeypatch.setattr(evr, "route_to_specialist", _fake_specialist)
    artifact, _ = await _run_workflow(
        EngagementValueReportInput(period_start="2026-04-01", period_end="2026-06-01")
    )
    assert calls == []
    assert "No recorded activity in this period" in artifact
    assert "## Follow-through" not in artifact
    assert "1 follow-ups currently in flight" in artifact
    assert artifact.index("Looking ahead") < artifact.index("currently in flight")


def test_gatherer_totals_survive_the_listing_cap(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    conn = sqlite3.connect(str(db))
    for i in range(35):
        conn.execute(
            "INSERT INTO decisions (timestamp, domain, summary, rationale, "
            "outcome, tags, department) VALUES (?, 'ops', ?, '', '', '', '')",
            (f"2026-05-{(i % 28) + 1:02d}T09:00:00", f"Decision {i}"),
        )
    conn.commit()
    conn.close()

    activity = gather_engagement_activity(db, "2026-05-01", "2026-05-31T23:59:59")
    assert len(activity.decisions) == 30  # capped
    assert activity.decisions_total == 35  # truthful total

    from openexecutive.workflows.engagement_value_report import _of_total

    assert _of_total(activity.decisions, activity.decisions_total) == " (showing 30 of 35)"
    assert _of_total(activity.decisions[:5], 5) == ""
