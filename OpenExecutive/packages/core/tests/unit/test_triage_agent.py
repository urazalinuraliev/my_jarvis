"""Tests for the TriageAgent — verifies prompt context assembly + decision parsing.

The Anthropic client is patched so no real API call is made.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openexecutive.agents.triage import TRIAGE_TOOL, TriageAgent, _parse_decision
from openexecutive.alerts.models import (
    AlertChannel,
    AlertEvent,
    AlertSeverity,
)


def _fake_response(tool_input: dict):
    """Build a fake anthropic Message with one tool_use content block."""
    block = SimpleNamespace(type="tool_use", name="emit_alert_decision", input=tool_input)
    return SimpleNamespace(content=[block])


def test_triage_model_follows_routing_model(monkeypatch) -> None:
    """Triage must use the configured routing model, not a hardcoded Claude
    slug — otherwise an Anthropic-free (local / OpenRouter) deployment can't
    run the alert pipeline. The property imports get_settings from
    openexecutive.config at call time, so patch it there."""
    monkeypatch.setattr(
        "openexecutive.config.get_settings",
        lambda: SimpleNamespace(routing_model="llama3.3"),
    )
    assert TriageAgent().model == "llama3.3"


def test_triage_returns_parsed_decision_and_passes_context() -> None:
    fake_input = {
        "alert": True,
        "severity": "urgent",
        "channels": ["web", "slack_dm", "persisted"],
        "headline": "Top customer cancelling",
        "body": "ARR loss of $200k",
        "suggested_action": "Call them in the next hour",
        "topic_tags": ["customer", "churn"],
        "dedup_key": "churn-acme",
        "reason_if_suppressed": "",
    }
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=_fake_response(fake_input)))
    )

    agent = TriageAgent()
    decision = asyncio.run(
        agent.triage(
            AlertEvent(
                source="email",
                external_id="msg-1",
                subject="Cancelling our subscription",
                body="We will be cancelling next month.",
            ),
            recent_alerts=[
                {
                    "headline": "Other thing",
                    "severity": "low",
                    "dedup_key": "x",
                    "topic_tags": ["finance"],
                }
            ],
            mute_patterns=["weekly_newsletter"],
            active_initiatives=[
                SimpleNamespace(title="Reduce churn", status="active", summary="Lower 6m churn to <2%")
            ],
            client=client,
        )
    )

    assert decision.alert is True
    assert decision.severity == AlertSeverity.URGENT
    assert AlertChannel.SLACK_DM in decision.channels
    assert AlertChannel.PERSISTED in decision.channels
    assert decision.headline == "Top customer cancelling"
    assert decision.dedup_key == "churn-acme"

    # Verify the user turn included the right context tags.
    call = client.messages.create.await_args
    user_msg = call.kwargs["messages"][0]["content"]
    assert "<event>" in user_msg
    assert "Cancelling our subscription" in user_msg
    assert "<recent_alerts>" in user_msg
    assert "Other thing" in user_msg
    assert "<muted_topics>" in user_msg
    assert "weekly_newsletter" in user_msg
    assert "<active_initiatives>" in user_msg
    assert "Reduce churn" in user_msg

    # Verify forced tool-use was requested.
    assert call.kwargs["tool_choice"] == {"type": "tool", "name": "emit_alert_decision"}
    assert call.kwargs["tools"] == [TRIAGE_TOOL]


def test_triage_falls_back_when_no_tool_use() -> None:
    """If the model replies with text only (or anything non-tool_use), we get
    a safe persisted-only fallback rather than crashing."""
    text_block = SimpleNamespace(type="text", text="Just chatting")
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(content=[text_block])))
    )
    agent = TriageAgent()
    decision = asyncio.run(
        agent.triage(
            AlertEvent(source="email", external_id="m-2", subject="hi", body="b"),
            client=client,
        )
    )
    assert decision.alert is False
    assert decision.channels == [AlertChannel.PERSISTED]
    assert decision.reason_if_suppressed == "no_decision"


def test_triage_swallows_client_exceptions() -> None:
    """LLM error → safe fallback decision, never propagates."""
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
    )
    agent = TriageAgent()
    decision = asyncio.run(
        agent.triage(
            AlertEvent(source="email", external_id="m-3", subject="x", body=""),
            client=client,
        )
    )
    assert decision.alert is False
    assert decision.reason_if_suppressed == "triage_error"


def test_parse_decision_coerces_persisted_in_and_caps_lengths() -> None:
    decision = _parse_decision(
        {
            "alert": True,
            "severity": "high",
            "channels": ["web"],
            "headline": "x" * 300,
            "body": "y" * 3000,
            "topic_tags": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
            "dedup_key": "k" * 200,
        }
    )
    assert decision.severity == AlertSeverity.HIGH
    assert AlertChannel.PERSISTED in decision.channels
    assert len(decision.headline) <= 200
    assert len(decision.body) <= 2000
    assert len(decision.topic_tags) <= 8
    assert len(decision.dedup_key) <= 120


def test_parse_decision_unknown_severity_falls_to_low() -> None:
    decision = _parse_decision({"alert": True, "severity": "OMG_CRITICAL", "channels": []})
    assert decision.severity == AlertSeverity.LOW
    assert decision.channels == [AlertChannel.PERSISTED]


def test_triage_prompt_external_section_covers_every_registered_adapter() -> None:
    """Sync guard against drift: every monitoring adapter in the runtime
    registry must be named in the triage prompt's '## External Signals' SECTION
    (not merely somewhere in the prompt). If a new adapter's source is missing
    there, triage won't trust it or emit its `external:*` tags — which is
    exactly what kept query/edgar/page_watch out of the briefing's Monitoring
    lane. Asserting against `_REGISTRY` rather than a hardcoded list means
    adding an adapter without documenting it here fails this test."""
    from openexecutive.monitoring.sources import _REGISTRY
    from openexecutive.prompts.triage_prompt import TRIAGE_PROMPT

    start = TRIAGE_PROMPT.index("## External Signals")
    end = TRIAGE_PROMPT.index("## Output Field Requirements", start)
    section = TRIAGE_PROMPT[start:end]

    assert _REGISTRY, "expected the source adapter registry to be populated"
    for kind in _REGISTRY:
        assert kind in section, (
            f"triage '## External Signals' section omits registered adapter {kind!r}"
        )
