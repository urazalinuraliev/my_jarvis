"""Anthropic tool definition + handler for the Ask OE form-fill tier.

``propose_form_values`` lets the Executive propose values for a form the
user currently has on screen (the Ask OE side panel sends the form's
descriptor inside a ``<page_context>`` block in the user turn). The
proposal is delivered to the client as a ``form_patch`` SSE event; the UI
places the values into the form as highlighted suggestions and the user
reviews and saves through the form's normal submit path. The tool itself
never persists anything server-side.

Cache note: this tool is ALWAYS present in the Executive's tool list —
tool definitions sit at the top of the cached prompt prefix, so adding it
conditionally (only when a form is on screen) would invalidate the tools
cache and every downstream system block whenever requests alternate
between panel and non-panel turns. The description gates usage instead.

Pattern matches ``orchestrator/watchlist_tools.py`` — JSON in / JSON out,
audit via the generic skill-tool ``tool_invocation`` logging in the agent
loop.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

PROPOSE_FORM_VALUES = "propose_form_values"


PROPOSE_FORM_VALUES_TOOL: dict[str, Any] = {
    "name": PROPOSE_FORM_VALUES,
    "description": (
        "Propose values for the form currently on the user's screen. ONLY "
        "use this when the user turn contains a <page_context> block with a "
        "FORM ON SCREEN descriptor — never otherwise. Pass the descriptor's "
        "form_id and a `fields` object mapping field names (exactly as "
        "listed in the descriptor) to proposed values; for fields of type "
        "json, pass the structured value itself, not a JSON-encoded string. "
        "The values are placed into the form as highlighted suggestions — "
        "the user reviews them and clicks Save themselves. This tool never "
        "saves, submits, or persists anything. Propose only fields you have "
        "a confident value for; omit the rest."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "form_id": {
                "type": "string",
                "description": "The form_id from the FORM ON SCREEN descriptor.",
            },
            "fields": {
                "type": "object",
                "description": (
                    "Field-name → proposed-value map. Keys must match the "
                    "descriptor's field names exactly."
                ),
            },
            "rationale": {
                "type": "string",
                "description": "One or two sentences on why these values.",
            },
        },
        "required": ["form_id", "fields"],
    },
}


FORM_TOOLS: list[dict[str, Any]] = [PROPOSE_FORM_VALUES_TOOL]


async def handle_propose_form_values(tool_input: dict[str, Any]) -> str:
    """Acknowledge the proposal so the model knows it reached the form.

    Delivery to the client happens in the agent loop (a ``form_patch``
    SSE event built from the same tool_input) — this handler only
    validates shape and reports back.
    """
    form_id = str(tool_input.get("form_id", "")).strip()
    fields = tool_input.get("fields")
    if not form_id:
        return json.dumps({"error": "form_id is required"})
    if not isinstance(fields, dict) or not fields:
        return json.dumps(
            {"error": "fields must be a non-empty object mapping field names to values"}
        )
    return json.dumps(
        {
            "status": "delivered",
            "form_id": form_id,
            "field_count": len(fields),
            "note": (
                "Values were placed into the form as highlighted suggestions. "
                "The user will review and save manually — do not claim "
                "anything was saved or submitted."
            ),
        }
    )


def build_form_patch_event(
    tool_input: dict[str, Any], iteration: int
) -> dict[str, Any]:
    """SSE event dict the chat route forwards verbatim to the panel."""
    fields = tool_input.get("fields")
    return {
        "type": "form_patch",
        "form_id": str(tool_input.get("form_id", "")),
        "fields": fields if isinstance(fields, dict) else {},
        "rationale": str(tool_input.get("rationale", "")),
        "iteration": iteration,
    }


FORM_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    PROPOSE_FORM_VALUES: handle_propose_form_values,
}


__all__ = [
    "FORM_TOOLS",
    "FORM_TOOL_HANDLERS",
    "PROPOSE_FORM_VALUES",
    "PROPOSE_FORM_VALUES_TOOL",
    "build_form_patch_event",
    "handle_propose_form_values",
]
