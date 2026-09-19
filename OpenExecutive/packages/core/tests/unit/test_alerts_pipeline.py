"""Tests for alert pipeline rules: preferences, mute checks, dispatch dispatch."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openexecutive.alerts.models import (
    AlertChannel,
    AlertEvent,
    AlertSeverity,
    TriageDecision,
    UserPreferences,
)
from openexecutive.alerts.preferences import (
    matches_mute,
    resolve_channels,
    save_preferences,
)
from openexecutive.alerts.store import add_mute, initialize_db, list_alerts


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "alerts.db"
    initialize_db(db_path)
    return db_path


def test_resolve_channels_intersects_with_enabled() -> None:
    prefs = UserPreferences(
        severity_threshold=AlertSeverity.LOW,
        channels_enabled=[AlertChannel.WEB, AlertChannel.PERSISTED],
    )
    out = resolve_channels(
        [AlertChannel.WEB, AlertChannel.SLACK_DM, AlertChannel.EMAIL],
        AlertSeverity.HIGH,
        prefs,
    )
    assert AlertChannel.WEB in out
    assert AlertChannel.SLACK_DM not in out
    assert AlertChannel.PERSISTED in out


def test_resolve_channels_drops_below_threshold() -> None:
    prefs = UserPreferences(severity_threshold=AlertSeverity.HIGH)
    out = resolve_channels(
        [AlertChannel.WEB, AlertChannel.PERSISTED],
        AlertSeverity.MEDIUM,
        prefs,
    )
    assert out == [AlertChannel.PERSISTED]


def test_resolve_channels_quiet_hours_suppresses_non_urgent() -> None:
    prefs = UserPreferences(
        severity_threshold=AlertSeverity.LOW,
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
        quiet_hours_tz="UTC",
    )
    out = resolve_channels(
        [AlertChannel.WEB, AlertChannel.PERSISTED],
        AlertSeverity.HIGH,
        prefs,
    )
    assert out == [AlertChannel.PERSISTED]


def test_resolve_channels_quiet_hours_passes_urgent_through() -> None:
    prefs = UserPreferences(
        severity_threshold=AlertSeverity.LOW,
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
        quiet_hours_tz="UTC",
    )
    out = resolve_channels(
        [AlertChannel.WEB, AlertChannel.SLACK_DM, AlertChannel.PERSISTED],
        AlertSeverity.URGENT,
        prefs,
    )
    assert AlertChannel.WEB in out
    assert AlertChannel.SLACK_DM in out


def test_resolve_channels_always_includes_persisted() -> None:
    prefs = UserPreferences(
        severity_threshold=AlertSeverity.LOW,
        channels_enabled=[AlertChannel.WEB],  # PERSISTED missing on purpose
    )
    out = resolve_channels(
        [AlertChannel.WEB],
        AlertSeverity.HIGH,
        prefs,
    )
    assert AlertChannel.PERSISTED in out


def test_matches_mute_substring_case_insensitive() -> None:
    assert matches_mute(["customer", "churn"], ["CHURN"])
    assert matches_mute(["hiring-pipeline"], ["hiring"])
    assert not matches_mute(["finance"], ["legal"])
    assert not matches_mute([], ["anything"])
    assert not matches_mute(["a"], [])


def test_save_and_reload_preferences(db: Path) -> None:
    prefs = UserPreferences(
        severity_threshold=AlertSeverity.HIGH,
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        channels_enabled=[AlertChannel.WEB, AlertChannel.PERSISTED],
    )
    save_preferences(prefs, db_path=db)

    from openexecutive.alerts.preferences import get_preferences

    loaded = get_preferences(db_path=db)
    assert loaded.severity_threshold == AlertSeverity.HIGH
    assert loaded.quiet_hours_start == "22:00"
    assert loaded.channels_enabled == [AlertChannel.WEB, AlertChannel.PERSISTED]


def test_evaluate_and_dispatch_persists_alert_and_publishes(monkeypatch, db: Path) -> None:
    """End-to-end pipeline test with TriageAgent stubbed."""
    from openexecutive.agents import triage as triage_module
    from openexecutive.alerts import pipeline, sse_bus

    async def fake_triage(self, event, **kwargs):  # noqa: ARG001 - signature match
        return TriageDecision(
            alert=True,
            severity=AlertSeverity.HIGH,
            channels=[AlertChannel.WEB, AlertChannel.PERSISTED],
            headline="Stub alert",
            body="A real signal",
            suggested_action="Reply within an hour",
            topic_tags=["customer"],
            dedup_key="stub-key",
        )

    monkeypatch.setattr(triage_module.TriageAgent, "triage", fake_triage)

    async def runner() -> tuple:
        queue = sse_bus.subscribe()
        try:
            decision, alert_id = await pipeline.evaluate_and_dispatch(
                AlertEvent(source="email", external_id="msg-x", subject="hi", body="world"),
                db_path=db,
            )
            received: list[dict] = []
            while not queue.empty():
                received.append(queue.get_nowait())
            return decision, alert_id, received
        finally:
            sse_bus.unsubscribe(queue)

    decision, alert_id, received = asyncio.run(runner())

    assert decision.alert is True
    assert alert_id is not None

    persisted = list_alerts(db_path=db)
    assert len(persisted) == 1
    assert persisted[0].headline == "Stub alert"
    assert persisted[0].channels_delivered == ["web", "persisted"]

    assert any(e.get("type") == "alert" for e in received)


def test_evaluate_post_mute_suppresses(monkeypatch, db: Path) -> None:
    """A muted topic produced by the LLM is suppressed after the call."""
    from openexecutive.agents import triage as triage_module
    from openexecutive.alerts import pipeline

    add_mute("hiring", db_path=db)

    async def fake_triage(self, event, **kwargs):  # noqa: ARG001
        return TriageDecision(
            alert=True,
            severity=AlertSeverity.HIGH,
            channels=[AlertChannel.WEB, AlertChannel.PERSISTED],
            headline="New senior eng candidate",
            body="...",
            topic_tags=["hiring"],
            dedup_key="cand-1",
        )

    monkeypatch.setattr(triage_module.TriageAgent, "triage", fake_triage)

    decision, alert_id = asyncio.run(
        pipeline.evaluate_and_dispatch(
            AlertEvent(source="email", external_id="m-mute", subject="cand", body="b"),
            db_path=db,
        )
    )

    assert decision.alert is False
    assert "muted" in decision.reason_if_suppressed
    assert alert_id is None
    assert list_alerts(db_path=db) == []


def test_in_quiet_hours_wraparound_window() -> None:
    """A 22:00 → 07:00 window correctly straddles midnight."""
    from openexecutive.alerts.preferences import _in_quiet_hours

    prefs = UserPreferences(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_tz="UTC",
    )
    # 23:00 UTC — inside.
    assert _in_quiet_hours(prefs, now=datetime(2030, 1, 1, 23, 0, tzinfo=UTC))
    # 03:00 UTC — inside.
    assert _in_quiet_hours(prefs, now=datetime(2030, 1, 1, 3, 0, tzinfo=UTC))
    # 12:00 UTC — outside.
    assert not _in_quiet_hours(prefs, now=datetime(2030, 1, 1, 12, 0, tzinfo=UTC))
