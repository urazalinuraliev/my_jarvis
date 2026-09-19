"""WaitForHuman workflow primitive — pause/resume across async human replies.

A workflow yields a ``WaitForHumanEvent`` to pause itself at an approval
gate. The caller (scheduler cadence runner or workflow HTTP runner) calls
``save_checkpoint`` and exits; the run sits in ``status='awaiting_human'``.

The ``run_resumer`` background loop watches for timeouts.  The inbound
resolver (Slack / Telegram / email hooks) calls ``apply_resolution`` when
a human replies, which stores the ``WaitForHumanResolution`` and advances
the run to ``status='resolved'``.

Phase 6 note: full generator resume (deserialising the execution frame) is
deferred to Phase 7.  This module ships the data model and ``parse_decision``
— the pieces needed for timeout handling and resolution recording.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.85


class WaitForHumanEvent(BaseModel):
    """Yielded by a workflow step that requires human approval or input.

    The workflow runner serialises this to ``state_json`` in ``workflow_runs``
    and sets ``status='awaiting_human'``.
    """

    person_id: int
    question: str
    timeout_hours: int = 48
    on_timeout: Literal["escalate", "auto_proceed", "fail"] = "escalate"
    context_summary: str = ""
    expected_reply_shape: Literal[
        "approve_reject", "free_text", "numeric", "document"
    ] = "approve_reject"
    # Optional: department slug for escalation routing.
    department: str = ""
    # The outbound message id sent to the person — used by the inbound resolver
    # to match replies via explicit reference (tier 1).
    outbound_message_id: str = ""
    # Channel the question was sent on (e.g. "slack", "email", "telegram").
    channel: str = ""
    # Channel-specific address used (Slack user id, email address, chat_id str).
    channel_ref: str = ""


class WaitForHumanResolution(BaseModel):
    """Recorded when a human successfully replies to a WaitForHumanEvent."""

    run_id: str = ""
    reply_text: str
    source_channel: str
    source_message_id: str = ""
    parsed_decision: dict[str, Any] = Field(default_factory=dict)
    person_id: int
    resolved_at: str = ""


# ---------------------------------------------------------------------------
# Decision parser
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a structured reply parser. "
    "Extract the human's decision from their message and return JSON only. "
    "No markdown, no explanation — pure JSON object on a single line."
)

_SHAPE_PROMPTS: dict[str, str] = {
    "approve_reject": (
        'Return: {"decision": "approve|reject|defer", "note": "<brief reason, max 100 chars>"}\n'
        "Rules: approve = yes/ok/agreed/sounds good/LGTM; reject = no/denied/decline; "
        "defer = maybe later/need more info/not now. When ambiguous, choose defer."
    ),
    "free_text": (
        'Return: {"text": "<exact reply text, max 500 chars>"}'
    ),
    "numeric": (
        'Return: {"value": <number or null>, "unit": "<unit string or empty>"}\n'
        "Extract the primary numeric value. Null if no number is present."
    ),
    "document": (
        'Return: {"received": true, "text_preview": "<first 200 chars of content>"}'
    ),
}

_FALLBACKS: dict[str, dict[str, Any]] = {
    "approve_reject": {"decision": "defer", "note": "parse_error"},
    "free_text": {"text": ""},
    "numeric": {"value": None, "unit": ""},
    "document": {"received": False, "text_preview": ""},
}


async def parse_decision(text: str, expected_shape: str) -> dict[str, Any]:
    """Parse a human reply into a structured decision dict.

    Uses the Council-configurable ``utility_fast`` model (default
    ``settings.routing_model``) for low-latency parsing. Returns a safe
    fallback dict on API errors so callers never see None.
    """
    import json as _json

    from openexecutive.agents.utility_fast import get_fast_model

    shape_prompt = _SHAPE_PROMPTS.get(expected_shape, _SHAPE_PROMPTS["free_text"])
    fallback = _FALLBACKS.get(expected_shape, {"text": ""})

    try:
        from openexecutive.config import get_settings
        from openexecutive.providers import get_provider

        settings = get_settings()
        model = get_fast_model()
        response = await get_provider(model).messages_create(
            model=model,
            max_tokens=256,
            timeout=settings.utility_fast_timeout_s,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Parse this reply (expected shape: {expected_shape}):\n\n"
                        f"{shape_prompt}\n\n"
                        f"Reply to parse:\n{text[:1000]}"
                    ),
                }
            ],
        )
        # The SDK only emits text blocks for this prompt (no tools, no
        # thinking). The union-attr complaint mypy raises here is a false
        # positive at runtime; suppress rather than narrowing because the
        # existing tests rely on duck-typed block stubs that wouldn't pass
        # an isinstance(TextBlock) check.
        raw = response.content[0].text.strip() if response.content else ""  # type: ignore[union-attr]
        # Strip any accidental markdown fences.
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return _json.loads(raw)
    except Exception:
        logger.exception("parse_decision: failed for shape=%r text=%r", expected_shape, text[:80])
        return dict(fallback)
