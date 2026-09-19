"""Unit tests for the Ask OE ``propose_form_values`` tool.

The tool is proposal-only: the handler validates shape and acknowledges
delivery; the actual values reach the client as a ``form_patch`` SSE
event built by ``build_form_patch_event`` in the agent loop. Nothing is
persisted server-side.
"""
from __future__ import annotations

import json

import pytest

from openexecutive.orchestrator.form_tools import (
    FORM_TOOL_HANDLERS,
    FORM_TOOLS,
    PROPOSE_FORM_VALUES,
    PROPOSE_FORM_VALUES_TOOL,
    build_form_patch_event,
    handle_propose_form_values,
)


def test_tool_definition_shape() -> None:
    assert PROPOSE_FORM_VALUES_TOOL["name"] == PROPOSE_FORM_VALUES
    schema = PROPOSE_FORM_VALUES_TOOL["input_schema"]
    assert schema["required"] == ["form_id", "fields"]
    assert set(schema["properties"]) == {"form_id", "fields", "rationale"}
    # The description must gate usage on the page_context form descriptor —
    # the tool is always in the (cached) tool list, so the description is
    # the only thing stopping the model from calling it on normal turns.
    assert "<page_context>" in PROPOSE_FORM_VALUES_TOOL["description"]
    assert FORM_TOOLS == [PROPOSE_FORM_VALUES_TOOL]
    assert FORM_TOOL_HANDLERS[PROPOSE_FORM_VALUES] is handle_propose_form_values


@pytest.mark.asyncio
async def test_handler_acknowledges_delivery() -> None:
    result = json.loads(
        await handle_propose_form_values(
            {"form_id": "add_person", "fields": {"full_name": "Sara Chen"}}
        )
    )
    assert result["status"] == "delivered"
    assert result["form_id"] == "add_person"
    assert result["field_count"] == 1
    # The model must not be told anything was saved.
    assert "saved" not in result["status"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_input",
    [
        {"fields": {"a": 1}},  # missing form_id
        {"form_id": "", "fields": {"a": 1}},  # blank form_id
        {"form_id": "f"},  # missing fields
        {"form_id": "f", "fields": "not-a-dict"},
        {"form_id": "f", "fields": []},
        {"form_id": "f", "fields": {}},  # empty proposal is useless
    ],
)
async def test_handler_rejects_bad_shapes(tool_input: dict) -> None:
    result = json.loads(await handle_propose_form_values(tool_input))
    assert "error" in result


def test_build_form_patch_event_shape() -> None:
    event = build_form_patch_event(
        {
            "form_id": "workflow_builder",
            "fields": {"title": "Weekly competitor watch", "estimated_minutes": 10},
            "rationale": "Matches the requested cadence.",
        },
        iteration=2,
    )
    assert event == {
        "type": "form_patch",
        "form_id": "workflow_builder",
        "fields": {"title": "Weekly competitor watch", "estimated_minutes": 10},
        "rationale": "Matches the requested cadence.",
        "iteration": 2,
    }


def test_build_form_patch_event_tolerates_bad_input() -> None:
    """A malformed tool_input must still produce a well-shaped event dict —
    the SSE generator json-dumps it verbatim."""
    event = build_form_patch_event({"fields": "oops"}, iteration=1)
    assert event["type"] == "form_patch"
    assert event["form_id"] == ""
    assert event["fields"] == {}
    assert event["rationale"] == ""
