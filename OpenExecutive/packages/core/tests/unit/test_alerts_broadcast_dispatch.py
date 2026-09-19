"""Tests for the Shift 3 broadcast-channel dispatch path in the alerts pipeline.

Verifies that:
- The new DEPARTMENT_CHANNEL / COMPANY_BROADCAST channel enums exist.
- `dispatch_all` routes those channels through the broadcast tools.
- The department_slug / broadcast_integration routing context is
  passed correctly to the dispatchers.
- Missing routing context returns False (no silent silent no-op).
- The TriageDecision model carries the new optional fields.

The actual broadcast tool calls are stubbed — these tests verify the
routing layer, not the underlying integration HTTP paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openexecutive.alerts import dispatcher, store
from openexecutive.alerts.models import Alert, AlertChannel, TriageDecision


@pytest.fixture()
def alerts_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated alerts DB initialized so dispatch_all's update_delivery
    has a row to write back to."""
    db = tmp_path / "alerts.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    store.initialize_db(db)
    return db


def _make_alert(headline: str = "Burn trending high") -> Alert:
    return Alert(
        id=1,
        source="department_check_in",
        severity="high",
        headline=headline,
        body="Burn rate up 18% MoM.",
        suggested_action="Review next week's spend.",
        topic_tags=["finance"],
        created_at="2026-05-26T08:00:00Z",
    )


# ---------------------------------------------------------------------------
# Model surface
# ---------------------------------------------------------------------------

def test_alert_channel_has_new_broadcast_values() -> None:
    assert AlertChannel.DEPARTMENT_CHANNEL.value == "department_channel"
    assert AlertChannel.COMPANY_BROADCAST.value == "company_broadcast"


def test_triage_decision_has_broadcast_routing_fields() -> None:
    decision = TriageDecision(
        alert=True,
        channels=[AlertChannel.DEPARTMENT_CHANNEL],
        department_slug="marketing",
        broadcast_integration="slack",
    )
    assert decision.department_slug == "marketing"
    assert decision.broadcast_integration == "slack"


def test_triage_decision_broadcast_fields_default_empty() -> None:
    decision = TriageDecision(alert=True, channels=[AlertChannel.WEB])
    assert decision.department_slug == ""
    assert decision.broadcast_integration == ""


# ---------------------------------------------------------------------------
# Dispatcher routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_department_channel_calls_broadcast_tool(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the alert's channels contain DEPARTMENT_CHANNEL, the dispatcher
    must invoke `handle_send_department_message` with the routed args."""
    captured: dict[str, Any] = {}

    async def _stub_dept_handler(payload: dict[str, Any]) -> str:
        captured.update(payload)
        return '{"status": "sent", "channel": "C123"}'

    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_department_message", _stub_dept_handler)

    alert = _make_alert()
    # Persist the alert so update_delivery has a row to update.
    alert.id = store.insert_alert(
        source=alert.source, external_id="ext-1", severity=alert.severity,
        headline=alert.headline, body=alert.body,
        suggested_action=alert.suggested_action,
        topic_tags=alert.topic_tags, dedup_key="test-1", db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.DEPARTMENT_CHANNEL],
        db_path=alerts_db,
        department_slug="marketing",
        broadcast_integration="slack",
    )

    assert "department_channel" in attempted
    assert "department_channel" in delivered
    assert captured["department_slug"] == "marketing"
    assert captured["integration"] == "slack"
    assert "Burn trending high" in captured["text"]
    assert "Review next week's spend." in captured["text"]


@pytest.mark.asyncio
async def test_department_channel_missing_slug_returns_false(
    alerts_db: Path,
) -> None:
    """Without a slug the dispatch can't resolve a target — fail loudly
    rather than send to nobody."""
    alert = _make_alert()
    alert.id = store.insert_alert(
        source=alert.source, external_id="ext-2", severity=alert.severity,
        headline=alert.headline, body=alert.body, dedup_key="test-2",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.DEPARTMENT_CHANNEL],
        db_path=alerts_db,
        department_slug="",
        broadcast_integration="slack",
    )
    assert "department_channel" in attempted
    assert "department_channel" not in delivered


@pytest.mark.asyncio
async def test_company_broadcast_calls_broadcast_tool(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _stub_company_handler(payload: dict[str, Any]) -> str:
        captured.update(payload)
        return '{"status": "sent", "channel": "C99GENERAL"}'

    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_company_broadcast", _stub_company_handler)

    alert = _make_alert("Q3 plan shipped")
    alert.id = store.insert_alert(
        source=alert.source, external_id="ext-3", severity=alert.severity,
        headline=alert.headline, body=alert.body, dedup_key="test-3",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.COMPANY_BROADCAST],
        db_path=alerts_db,
        broadcast_integration="slack",
    )

    assert "company_broadcast" in attempted
    assert "company_broadcast" in delivered
    assert captured["integration"] == "slack"
    assert "Q3 plan shipped" in captured["text"]


@pytest.mark.asyncio
async def test_company_broadcast_missing_integration_returns_false(
    alerts_db: Path,
) -> None:
    alert = _make_alert()
    alert.id = store.insert_alert(
        source=alert.source, external_id="ext-4", severity=alert.severity,
        headline=alert.headline, body=alert.body, dedup_key="test-4",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.COMPANY_BROADCAST],
        db_path=alerts_db,
        broadcast_integration="",
    )
    assert "company_broadcast" in attempted
    assert "company_broadcast" not in delivered


def test_triage_parser_propagates_broadcast_fields() -> None:
    """The triage tool's LLM response must reach the TriageDecision —
    if `_parse_decision` drops `department_slug` / `broadcast_integration`,
    the dispatcher receives empty strings and the broadcast becomes a no-op
    even when the model picked a broadcast channel.

    Regression test for a round-2-review finding.
    """
    from openexecutive.agents.triage import _parse_decision

    raw = {
        "alert": True,
        "severity": "high",
        "channels": ["web", "persisted", "department_channel"],
        "headline": "Marketing Q3 goal at risk",
        "body": "Off by 20%.",
        "topic_tags": ["marketing"],
        "dedup_key": "mkt-q3",
        "department_slug": "marketing",
        "broadcast_integration": "slack",
    }
    decision = _parse_decision(raw)
    assert decision.department_slug == "marketing"
    assert decision.broadcast_integration == "slack"
    assert AlertChannel.DEPARTMENT_CHANNEL in decision.channels


def test_triage_parser_rejects_invalid_broadcast_integration() -> None:
    """A bogus broadcast_integration value drops to empty string rather
    than crashing parser. Dispatcher will return False on the missing
    context — graceful degradation."""
    from openexecutive.agents.triage import _parse_decision

    raw = {
        "alert": True,
        "severity": "medium",
        "channels": ["company_broadcast", "persisted"],
        "headline": "Q3 plan shipped",
        "body": ".",
        "broadcast_integration": "bogus",  # not in enum
    }
    decision = _parse_decision(raw)
    assert decision.broadcast_integration == ""


def test_triage_parser_omits_broadcast_fields_when_absent() -> None:
    """When neither broadcast channel is picked, the fields default to ''
    on the decision — not None, not missing."""
    from openexecutive.agents.triage import _parse_decision

    raw = {
        "alert": True,
        "severity": "low",
        "channels": ["persisted"],
        "headline": "FYI",
        "body": ".",
    }
    decision = _parse_decision(raw)
    assert decision.department_slug == ""
    assert decision.broadcast_integration == ""


@pytest.mark.asyncio
async def test_privacy_invariant_does_not_overmatch_competitor(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`competitor` MUST broadcast — the substring-vs-exact overmatch
    bug in round-1 fix would have refused this; the round-2 fix uses
    exact match so `competitor` and `compliance` pass through.

    Regression test for a round-2-review finding.
    """
    sent = {"n": 0}

    async def _stub_dept(_payload: dict[str, Any]) -> str:
        sent["n"] += 1
        return '{"status": "sent"}'
    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_department_message", _stub_dept)

    alert = _make_alert("New competitor launched a similar product")
    alert.topic_tags = ["competitor", "marketing"]
    alert.id = store.insert_alert(
        source=alert.source, external_id="ovr-1", severity=alert.severity,
        headline=alert.headline, body=alert.body,
        topic_tags=alert.topic_tags, dedup_key="ovr-1",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.DEPARTMENT_CHANNEL],
        db_path=alerts_db,
        department_slug="marketing",
        broadcast_integration="slack",
    )
    assert "department_channel" in delivered
    assert sent["n"] == 1


@pytest.mark.asyncio
async def test_resolve_channels_keeps_broadcast_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-user `channels_enabled` preference must NOT drop broadcast
    channels — they're org-routing, not personal preference.

    Regression test for the case where the default channels_enabled
    set ({web, slack_dm, email, persisted}) silently filtered out
    department_channel / company_broadcast before dispatch_all saw
    them, making the broadcast feature dead-on-arrival.
    """
    from openexecutive.alerts.models import (
        AlertSeverity,
        UserPreferences,
    )
    from openexecutive.alerts.preferences import resolve_channels

    prefs = UserPreferences()  # defaults — no broadcast channels enabled
    requested = [
        AlertChannel.WEB,
        AlertChannel.PERSISTED,
        AlertChannel.DEPARTMENT_CHANNEL,
        AlertChannel.COMPANY_BROADCAST,
    ]
    resolved = resolve_channels(requested, AlertSeverity.HIGH, prefs)
    assert AlertChannel.DEPARTMENT_CHANNEL in resolved
    assert AlertChannel.COMPANY_BROADCAST in resolved


@pytest.mark.asyncio
async def test_privacy_invariant_blocks_board_broadcast(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'board'-tagged alert MUST NOT broadcast, even when triage routed
    it to a department channel. Defence-in-depth backstop on top of the
    prompt-level rule."""
    sent = {"n": 0}

    async def _stub_dept(_payload: dict[str, Any]) -> str:
        sent["n"] += 1
        return '{"status": "sent"}'
    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_department_message", _stub_dept)

    alert = _make_alert()
    alert.topic_tags = ["board", "investor"]
    alert.id = store.insert_alert(
        source=alert.source, external_id="priv-1", severity=alert.severity,
        headline=alert.headline, body=alert.body,
        topic_tags=alert.topic_tags, dedup_key="priv-1",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.DEPARTMENT_CHANNEL],
        db_path=alerts_db,
        department_slug="finance",
        broadcast_integration="slack",
    )
    assert "department_channel" in attempted
    assert "department_channel" not in delivered
    assert sent["n"] == 0  # broadcast handler was never called


@pytest.mark.asyncio
async def test_privacy_invariant_blocks_comp_company_broadcast(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror of the dept test for company_broadcast — a comp-tagged
    alert can't reach the company channel either."""
    sent = {"n": 0}

    async def _stub_company(_payload: dict[str, Any]) -> str:
        sent["n"] += 1
        return '{"status": "sent"}'
    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_company_broadcast", _stub_company)

    alert = _make_alert("Q3 comp refresh decisions")
    alert.topic_tags = ["compensation", "hiring"]
    alert.id = store.insert_alert(
        source=alert.source, external_id="priv-2", severity=alert.severity,
        headline=alert.headline, body=alert.body,
        topic_tags=alert.topic_tags, dedup_key="priv-2",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.COMPANY_BROADCAST],
        db_path=alerts_db,
        broadcast_integration="slack",
    )
    assert "company_broadcast" in attempted
    assert "company_broadcast" not in delivered
    assert sent["n"] == 0


@pytest.mark.asyncio
async def test_mixed_channels_routes_each_correctly(
    alerts_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An alert can have both per-person and broadcast channels; each
    dispatcher gets the inputs it needs and the simple channels don't see
    the routing-context kwargs."""
    async def _stub_dept(payload: dict[str, Any]) -> str:
        return '{"status": "sent"}'
    import openexecutive.orchestrator.broadcast_tools as bt
    monkeypatch.setattr(bt, "handle_send_department_message", _stub_dept)

    alert = _make_alert()
    alert.id = store.insert_alert(
        source=alert.source, external_id="ext-5", severity=alert.severity,
        headline=alert.headline, body=alert.body, dedup_key="test-5",
        db_path=alerts_db,
    )
    attempted, delivered = await dispatcher.dispatch_all(
        alert,
        [AlertChannel.WEB, AlertChannel.PERSISTED, AlertChannel.DEPARTMENT_CHANNEL],
        db_path=alerts_db,
        department_slug="finance",
        broadcast_integration="slack",
    )
    assert set(attempted) == {"web", "persisted", "department_channel"}
    assert "web" in delivered
    assert "persisted" in delivered
    assert "department_channel" in delivered
