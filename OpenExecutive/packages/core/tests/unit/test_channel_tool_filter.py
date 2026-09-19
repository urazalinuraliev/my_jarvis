"""Tests for filter_tools_for_configured_channels.

The synthesis loops (executive_research / executive_reflection) must only
offer the Executive channels that actually have a token, otherwise the
model routes findings into e.g. send_slack_dm when Slack is unconfigured
and every call fails "slack is not configured".
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

from openexecutive.orchestrator.broadcast_tools import (
    SEND_COMPANY_BROADCAST_TOOL,
    SEND_DEPARTMENT_MESSAGE_TOOL,
)
from openexecutive.orchestrator.schedule_tools import (
    SEND_DISCORD_DM_TOOL,
    SEND_SLACK_DM_TOOL,
    SEND_TELEGRAM_MESSAGE_TOOL,
    configured_integrations,
    filter_tools_for_configured_channels,
)


def _settings(*, slack=None, discord=None, telegram=None):
    return SimpleNamespace(
        slack_bot_token=slack,
        discord_bot_token=discord,
        telegram_bot_token=telegram,
    )


def _names(tools):
    return {t["name"] for t in tools}


def _all_channel_tools():
    # Fresh deep copies so a mutating bug would be caught (the input must
    # never be mutated in place).
    return [
        copy.deepcopy(SEND_SLACK_DM_TOOL),
        copy.deepcopy(SEND_DISCORD_DM_TOOL),
        copy.deepcopy(SEND_TELEGRAM_MESSAGE_TOOL),
        copy.deepcopy(SEND_DEPARTMENT_MESSAGE_TOOL),
        copy.deepcopy(SEND_COMPANY_BROADCAST_TOOL),
        {"name": "lookup_person", "input_schema": {}},
    ]


def test_configured_integrations_reads_tokens():
    assert configured_integrations(_settings()) == set()
    assert configured_integrations(_settings(discord="x")) == {"discord"}
    assert configured_integrations(
        _settings(slack="a", discord="b", telegram="c")
    ) == {"slack", "discord", "telegram"}


def test_discord_only_keeps_discord_drops_slack_and_telegram():
    out = filter_tools_for_configured_channels(
        _all_channel_tools(), _settings(discord="tok")
    )
    names = _names(out)
    assert "send_discord_dm" in names
    assert "send_slack_dm" not in names
    assert "send_telegram_message" not in names
    # Non-channel tool always survives.
    assert "lookup_person" in names
    # Broadcast tool survives but its enum is narrowed to discord only.
    dept = next(t for t in out if t["name"] == "send_department_message")
    assert dept["input_schema"]["properties"]["integration"]["enum"] == ["discord"]


def test_slack_only_keeps_slack_drops_others():
    out = filter_tools_for_configured_channels(
        _all_channel_tools(), _settings(slack="tok")
    )
    names = _names(out)
    assert "send_slack_dm" in names
    assert "send_discord_dm" not in names
    assert "send_telegram_message" not in names
    bc = next(t for t in out if t["name"] == "send_company_broadcast")
    assert bc["input_schema"]["properties"]["integration"]["enum"] == ["slack"]


def test_none_configured_drops_all_channel_tools():
    out = filter_tools_for_configured_channels(_all_channel_tools(), _settings())
    names = _names(out)
    assert "send_slack_dm" not in names
    assert "send_discord_dm" not in names
    assert "send_telegram_message" not in names
    # Broadcast tools have no surviving channel → dropped entirely.
    assert "send_department_message" not in names
    assert "send_company_broadcast" not in names
    # Non-channel tools remain.
    assert names == {"lookup_person"}


def test_message_person_dropped_when_no_dm_channel_configured():
    mp = {"name": "message_person", "input_schema": {"properties": {}}}
    # No DM channel → message_person has nothing to route to → dropped.
    assert _names(filter_tools_for_configured_channels([mp], _settings())) == set()
    # Any DM channel configured → message_person survives.
    out = filter_tools_for_configured_channels([mp], _settings(discord="tok"))
    assert "message_person" in _names(out)


def test_all_configured_is_passthrough_and_preserves_enum_order():
    tools = _all_channel_tools()
    out = filter_tools_for_configured_channels(
        tools, _settings(slack="a", discord="b", telegram="c")
    )
    assert _names(out) == _names(tools)
    dept = next(t for t in out if t["name"] == "send_department_message")
    assert dept["input_schema"]["properties"]["integration"]["enum"] == [
        "slack",
        "discord",
        "telegram",
    ]


def test_partial_config_narrows_enum_preserving_order():
    out = filter_tools_for_configured_channels(
        _all_channel_tools(), _settings(slack="a", discord="b")
    )
    names = _names(out)
    assert "send_slack_dm" in names
    assert "send_discord_dm" in names
    assert "send_telegram_message" not in names
    dept = next(t for t in out if t["name"] == "send_department_message")
    # Order follows the source enum (slack before discord), telegram dropped.
    assert dept["input_schema"]["properties"]["integration"]["enum"] == [
        "slack",
        "discord",
    ]


def test_empty_string_token_is_treated_as_unconfigured():
    out = filter_tools_for_configured_channels(
        _all_channel_tools(), _settings(slack="", discord="tok")
    )
    names = _names(out)
    assert "send_slack_dm" not in names
    assert "send_discord_dm" in names


def test_non_channel_enum_value_handling():
    # A hypothetical broadcast-style tool whose enum mixes a channel with a
    # non-channel value. With no channel configured, no channel survives so
    # the tool is dropped (it can't post anywhere).
    weird = {
        "name": "weird_broadcast",
        "input_schema": {
            "properties": {"integration": {"enum": ["slack", "webhook"]}}
        },
    }
    assert filter_tools_for_configured_channels([weird], _settings()) == []
    # With slack configured, the tool survives and keeps both values.
    kept = filter_tools_for_configured_channels([weird], _settings(slack="x"))
    assert kept[0]["input_schema"]["properties"]["integration"]["enum"] == [
        "slack",
        "webhook",
    ]


def test_does_not_mutate_input_tools():
    tools = _all_channel_tools()
    before = copy.deepcopy(tools)
    filter_tools_for_configured_channels(tools, _settings(discord="tok"))
    # The original list's tool dicts must be untouched.
    assert tools == before


# --------------------------------------------------------------------- #
# Synthesis prompt gating — the routing menu must name only configured
# DM channels. The tool list is gated by filter_tools_for_configured_
# channels (above); the PROMPT is gated by _build_synthesis_system, so a
# deployment without Slack is never told to "PREFER send_slack_dm".
# --------------------------------------------------------------------- #
from openexecutive.workflows.executive_research import (  # noqa: E402
    _build_synthesis_system,
)


def test_synthesis_prompt_routes_dms_via_message_person():
    # DMs go through message_person (server resolves the channel id); the raw
    # per-channel send_*_dm tools must NOT be named — the model kept passing
    # the wrong id into them.
    sys = _build_synthesis_system({"discord", "telegram"})
    assert "message_person" in sys
    assert "send_discord_dm" not in sys
    assert "send_telegram_message" not in sys
    assert "send_slack_dm" not in sys
    # Steer off lookup_person — the roster is provided in the findings turn.
    assert "lookup_person" in sys and "do NOT call lookup_person" in sys.replace("Do NOT", "do NOT")


def test_synthesis_prompt_marks_dm_unavailable_when_no_channel():
    sys = _build_synthesis_system(set())
    assert "message_person" not in sys
    assert "UNAVAILABLE" in sys


def test_synthesis_prompt_offers_message_person_when_any_channel_configured():
    sys = _build_synthesis_system({"slack", "discord", "telegram"})
    assert "message_person" in sys
    # Raw per-channel DM tools are never named in synthesis.
    assert "send_slack_dm" not in sys
    assert "send_discord_dm" not in sys
    # Static scaffolding must survive the refactor.
    assert "ROUTING BUDGET" in sys
    assert "DEFAULT IS IGNORE" in sys


# Same gating applies to executive_reflection's audience rule.
from openexecutive.workflows.executive_reflection import (  # noqa: E402
    _build_reflection_system,
)


def test_reflection_prompt_routes_dms_via_message_person():
    # DMs go through message_person; raw per-channel send tools are never named.
    sys = _build_reflection_system({"discord", "telegram"})
    assert "message_person" in sys
    assert "send_discord_dm" not in sys
    assert "send_telegram_message" not in sys
    assert "send_slack_dm" not in sys
    # Steer off lookup_person — the roster is provided in the turn.
    assert "do NOT call" in sys.replace("Do NOT", "do NOT") and "lookup_person" in sys


def test_reflection_prompt_steers_away_from_dm_when_no_channel():
    sys = _build_reflection_system(set())
    assert "message_person" not in sys
    assert "send_slack_dm" not in sys
    assert "send_discord_dm" not in sys
    assert "send_telegram_message" not in sys
    assert "no direct-message channel is configured" in sys
    # Static scaffolding must survive the refactor.
    assert "morning solo standup" in sys
    assert "send_department_message" in sys


def test_synthesis_prompt_falls_back_to_lookup_when_no_roster():
    # With no roster in the turn, the model must be allowed to use lookup_person
    # — otherwise it has no way to get a person_id (the coherence bug).
    sys = _build_synthesis_system({"discord"}, has_roster=False)
    assert "message_person" in sys
    assert "lookup_person" in sys
    assert "do NOT call lookup_person" not in sys.replace("Do NOT", "do NOT")


def test_reflection_prompt_falls_back_to_lookup_when_no_roster():
    sys = _build_reflection_system({"discord"}, has_roster=False)
    assert "message_person" in sys
    assert "lookup_person" in sys
    assert "Do NOT call `lookup_person`" not in sys
