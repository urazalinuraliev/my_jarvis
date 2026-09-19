"""Inbound message resolver for WaitForHuman workflow pauses.

When a human sends a reply via Slack, Telegram, or email, this module
tries to match it to an ``awaiting_human`` workflow run.

Three-tier matching (highest priority first)
-------------------------------------------
1. **Explicit reference** — ``in_reply_to`` matches ``outbound_message_id``
   stored in the run's ``state_json``.  Most reliable; zero LLM cost.

2. **Single-candidate** — the person has exactly ONE ``awaiting_human`` run
   addressed to them on this channel, within the last 7 days.  Reliable
   when the human's workflow queue has exactly one open item.

3. **LLM disambiguation** — multiple candidates exist.  A single Haiku call
   picks the best match and returns a confidence score.  Below
   ``_CONFIDENCE_THRESHOLD`` (0.85) → return ``None`` (caller escalates).

Returns ``WaitForHumanResolution`` on a confident match, ``None`` otherwise.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import openexecutive.workflows.persistence as _wf_persistence
from openexecutive.workflows.wait_for_human import (
    _CONFIDENCE_THRESHOLD,
    WaitForHumanResolution,
    parse_decision,
)

logger = logging.getLogger(__name__)

_RECENCY_DAYS = 7


def _load_awaiting_runs(
    from_person_id: int | None,
    db_path: Path | None,
) -> list[dict]:
    """Return awaiting_human runs for this person, from the last _RECENCY_DAYS days."""
    all_runs = _wf_persistence.list_awaiting_runs(db_path=db_path)
    if not all_runs:
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=_RECENCY_DAYS)).isoformat()
    result = []
    for run in all_runs:
        if from_person_id is not None and run.get("awaiting_person_id") != from_person_id:
            continue
        if run.get("updated_at", "") < cutoff:
            continue
        result.append(run)
    return result


def _parse_state(run: dict) -> dict:
    raw = run.get("state_json") or "{}"
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


async def _make_resolution(
    *,
    run: dict,
    text: str,
    channel: str,
    message_id: str,
    person_id: int,
    expected_shape: str,
) -> WaitForHumanResolution:
    parsed = await parse_decision(text, expected_shape)
    return WaitForHumanResolution(
        run_id=run["run_id"],
        reply_text=text,
        source_channel=channel,
        source_message_id=message_id,
        parsed_decision=parsed,
        person_id=person_id,
        resolved_at=datetime.now(UTC).isoformat(),
    )


async def resolve_inbound_message(
    *,
    channel: str,
    channel_ref: str,
    from_person_id: int | None,
    text: str,
    message_id: str = "",
    in_reply_to: str = "",
    db_path: Path | None = None,
) -> WaitForHumanResolution | None:
    """Try to match an inbound message to an awaiting_human workflow run.

    Returns a ``WaitForHumanResolution`` on a confident match, ``None``
    if unmatched or confidence below threshold.
    """
    if not text.strip():
        return None

    candidates = _load_awaiting_runs(from_person_id, db_path)
    if not candidates:
        return None

    # ------------------------------------------------------------------ #
    # Tier 1: explicit in_reply_to match
    # If the caller supplied an explicit reference and it doesn't match any
    # open run, return None immediately — do NOT fall through to fuzzier
    # tiers with a stale reference (that would mis-match an unrelated run).
    # ------------------------------------------------------------------ #
    if in_reply_to:
        for run in candidates:
            state = _parse_state(run)
            stored_msg_id = state.get("outbound_message_id", "")
            if stored_msg_id and stored_msg_id == in_reply_to:
                logger.info(
                    "resolver: tier-1 match run_id=%s via in_reply_to=%s",
                    run["run_id"], in_reply_to,
                )
                return await _make_resolution(
                    run=run,
                    text=text,
                    channel=channel,
                    message_id=message_id,
                    person_id=from_person_id or run.get("awaiting_person_id") or 0,
                    expected_shape=state.get("expected_reply_shape", "approve_reject"),
                )
        # Explicit reference given but not matched — refuse to fall through.
        logger.debug(
            "resolver: in_reply_to=%r supplied but no matching run — returning None",
            in_reply_to,
        )
        return None

    # ------------------------------------------------------------------ #
    # Tier 2: single-candidate — exactly one open run on this channel
    # ------------------------------------------------------------------ #
    channel_matches = [
        run for run in candidates
        if _parse_state(run).get("channel") == channel
    ]

    if len(channel_matches) == 1:
        run = channel_matches[0]
        state = _parse_state(run)
        logger.info(
            "resolver: tier-2 match run_id=%s (single candidate on channel=%s)",
            run["run_id"], channel,
        )
        return await _make_resolution(
            run=run,
            text=text,
            channel=channel,
            message_id=message_id,
            person_id=from_person_id or run.get("awaiting_person_id") or 0,
            expected_shape=state.get("expected_reply_shape", "approve_reject"),
        )

    if len(channel_matches) == 0:
        logger.debug("resolver: no awaiting runs for channel=%s person=%s", channel, from_person_id)
        return None

    # ------------------------------------------------------------------ #
    # Tier 3: LLM disambiguation
    # ------------------------------------------------------------------ #
    logger.info(
        "resolver: tier-3 LLM disambiguation — %d candidates for person=%s",
        len(channel_matches), from_person_id,
    )
    chosen_run_id, confidence = await _llm_disambiguate(text, channel_matches)
    if chosen_run_id is None or confidence < _CONFIDENCE_THRESHOLD:
        logger.info(
            "resolver: LLM confidence %.2f below threshold %.2f — returning None",
            confidence, _CONFIDENCE_THRESHOLD,
        )
        return None

    matched = next((r for r in channel_matches if r["run_id"] == chosen_run_id), None)
    if matched is None:
        return None

    state = _parse_state(matched)
    logger.info(
        "resolver: tier-3 match run_id=%s confidence=%.2f", chosen_run_id, confidence
    )
    return await _make_resolution(
        run=matched,
        text=text,
        channel=channel,
        message_id=message_id,
        person_id=from_person_id or matched.get("awaiting_person_id") or 0,
        expected_shape=state.get("expected_reply_shape", "approve_reject"),
    )


async def _llm_disambiguate(
    text: str,
    candidates: list[dict],
) -> tuple[str | None, float]:
    """Ask Haiku to pick the best-matching run from multiple candidates.

    Returns (run_id, confidence). On failure returns (None, 0.0).
    """
    import json as _json

    candidate_summaries = "\n".join(
        f"[{i + 1}] run_id={r['run_id']} workflow={r.get('workflow_name','')} "
        f"title={r.get('title','')} "
        f"question={_parse_state(r).get('question','')[:120]}"
        for i, r in enumerate(candidates[:6])
    )

    prompt = (
        "A human sent this reply:\n"
        f"{text[:500]}\n\n"
        "Which of these open workflow pauses is it most likely responding to?\n\n"
        f"{candidate_summaries}\n\n"
        'Return JSON: {"run_id": "<chosen run_id>", "confidence": <0.0-1.0>}\n'
        "confidence = how certain you are this reply is for that run. "
        "If none fit well, set confidence below 0.85."
    )

    try:
        import asyncio

        from openexecutive.agents.utility_fast import get_fast_model
        from openexecutive.config import get_settings
        from openexecutive.providers import get_provider

        model = get_fast_model()
        response = await asyncio.wait_for(
            get_provider(model).messages_create(
                model=model,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=get_settings().utility_fast_timeout_s,
        )
        raw_text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
        raw = raw_text_blocks[0].text.strip() if raw_text_blocks else ""
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = _json.loads(raw)
        return data.get("run_id"), float(data.get("confidence", 0.0))
    except Exception:
        logger.exception("resolver: LLM disambiguation failed")
        return None, 0.0
