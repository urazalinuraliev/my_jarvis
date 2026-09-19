"""Anthropic tool definitions + handlers for managing department Goals.

These tools let the Executive update a Goal's `status` and/or `current`
progress text directly from a chat turn — used when the user reports
progress on a tracked Goal ("we shipped the billing migration") or a
setback ("we lost the Acme deal"). They close the loop that Phase A's
`department_check_in` workflow opened — chat-driven activity now feeds
the same `last_reviewed_at` column the cadence-driven review writes to.

Sit alongside `people_tools`, `schedule_tools`, `broadcast_tools`, and
`alert_tools` in the Executive's main tool loop. No authority gate —
the goal-mutation surface is principal-editable at any time through the
UI, so a chat-turn change is no riskier than a manual edit; the audit
row carries `rationale` for accountability.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_VALID_GOAL_STATUSES = ("on_track", "at_risk", "off_track")


LIST_DEPARTMENT_GOALS_TOOL: dict[str, Any] = {
    "name": "list_department_goals",
    "description": (
        "List a department's Goals with their ids, key_results, current "
        "progress, statuses, and last-reviewed timestamps. Use this to "
        "resolve a verbal goal reference ('the migration goal', "
        "'our Q2 ARR target') to a goal_id before calling "
        "update_department_goal. Returns a compact JSON list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "department_slug": {
                "type": "string",
                "description": (
                    "Lowercase slug from the department registry "
                    "(e.g. 'engineering', 'finance', 'marketing')."
                ),
            },
        },
        "required": ["department_slug"],
    },
}


UPDATE_DEPARTMENT_GOAL_TOOL: dict[str, Any] = {
    "name": "update_department_goal",
    "description": (
        "Update a department Goal's status, current-progress text, or "
        "both — based on something the user just told you. Call this "
        "when the user reports concrete progress on (or a setback to) a "
        "tracked Goal: 'we shipped the billing migration' (likely a "
        "current update + bump to on_track), 'lost the Acme deal' "
        "(status to at_risk or off_track), 'closed 40% of the ARR "
        "target' (current update). Use `list_department_goals` first "
        "if you don't already have the goal_id from earlier in the "
        "conversation. Do NOT use this to refuse and redirect to the "
        "UI — the user expects the update to just happen. Do NOT use "
        "for speculation or for goals the user is only asking advice "
        "on. Records ONE evidence-backed change per call: do not action "
        "a blanket 'update all my goals' / 'mark everything off track' "
        "instruction — without per-goal detail you have nothing real to "
        "record, so ask what concretely changed instead of sweeping "
        "every status. Every call is audited with the rationale you "
        "provide, and the principal can re-edit the goal in the UI at "
        "any time."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "department_slug": {
                "type": "string",
                "description": "Lowercase department slug owning the goal.",
            },
            "goal_id": {
                "type": "integer",
                "description": "Integer id of the goal (from list_department_goals).",
            },
            "status": {
                "type": "string",
                "enum": list(_VALID_GOAL_STATUSES),
                "description": (
                    "New status. Omit to leave the existing status unchanged. "
                    "Must supply at least one of `status` or `current`."
                ),
            },
            "current": {
                "type": "string",
                "description": (
                    "New human-readable progress text (e.g. '$750K of $1M ARR', "
                    "'cutover complete'). Overwrites the prior value. Omit to "
                    "leave unchanged. Must supply at least one of `status` or "
                    "`current`."
                ),
            },
            "rationale": {
                "type": "string",
                "description": (
                    "One short sentence: WHY this update — the goal-specific "
                    "thing the user said or that just happened. Required. Must "
                    "cite evidence for THIS goal, not a blanket reason reused "
                    "across many goals. Stored in the audit log (not on the "
                    "goal row) so future readers can see the provenance of "
                    "every change."
                ),
            },
        },
        "required": ["department_slug", "goal_id", "rationale"],
    },
}


DEPARTMENT_TOOLS: list[dict[str, Any]] = [
    LIST_DEPARTMENT_GOALS_TOOL,
    UPDATE_DEPARTMENT_GOAL_TOOL,
]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def _audit(
    tool: str,
    kind: str,
    ok: bool,
    summary: str,
    details: dict[str, Any],
    *,
    department: str | None = None,
) -> None:
    """Emit a `tool_invocation` audit row — mirrors `people_tools._audit`.

    Passes `department` as a top-level kwarg (not just inside `details`) so
    per-department audit queries via `audit_logger.query(department=…)`
    pick it up — the same plumbing the `department_check_in` workflow uses.

    Wrapped so a logger backend hiccup never breaks the chat turn — the
    handler returns its JSON response regardless.
    """
    try:
        from openexecutive.audit import log_event as audit_log

        audit_log(
            "tool_invocation",
            summary,
            actor="executive",
            department=department,
            details={"tool": tool, "kind": kind, "ok": ok, **details},
        )
    except Exception:  # noqa: BLE001 - audit must never break the tool path.
        logger.warning("department_tools: audit log failed", exc_info=True)


async def handle_list_department_goals(tool_input: dict[str, Any]) -> str:
    from openexecutive.departments import store as dept_store

    slug = str(tool_input.get("department_slug", "")).strip()
    if not slug:
        _audit(
            "list_department_goals", "read", False,
            "list_department_goals bad input: empty department_slug",
            {"error": "department_slug required"},
        )
        return json.dumps({"error": "department_slug is required"})

    try:
        goals = dept_store.list_goals(slug)
    except Exception as exc:
        logger.exception("list_department_goals: failed slug=%s", slug)
        _audit(
            "list_department_goals", "read", False,
            f"list_department_goals failed: {exc}",
            {"department_slug": slug, "error": str(exc)[:300]},
            department=slug,
        )
        return json.dumps({"error": str(exc)})

    out = [
        {
            "id": g.id,
            "key_result": g.key_result,
            "target": g.target,
            "current": g.current,
            "status": g.status,
            "period": f"{g.period_type} {g.period_value}".strip(),
            "last_reviewed_at": g.last_reviewed_at,
        }
        for g in goals
    ]
    _audit(
        "list_department_goals", "read", True,
        f"list_department_goals {slug}: {len(out)} goal(s)",
        {"department_slug": slug, "count": len(out)},
        department=slug,
    )
    return json.dumps({"department_slug": slug, "goals": out, "count": len(out)})


async def handle_update_department_goal(tool_input: dict[str, Any]) -> str:
    from openexecutive.departments import registry as dept_registry
    from openexecutive.departments import store as dept_store

    def _bad(err: str, **extra: Any) -> str:
        _audit(
            "update_department_goal", "write", False,
            f"update_department_goal bad input: {err}",
            {"error": err[:300], **extra},
            # `extra` may carry `department_slug` — surface it as the audit
            # row's top-level department tag too, when present.
            department=extra.get("department_slug"),
        )
        return json.dumps({"error": err})

    # ---- Input validation ----
    slug = str(tool_input.get("department_slug", "")).strip()
    if not slug:
        return _bad("department_slug is required")

    raw_goal_id = tool_input.get("goal_id")
    try:
        # `bool` is a subclass of `int` in Python — reject explicitly so a
        # `{"goal_id": true}` from a hallucinating model doesn't pass.
        if isinstance(raw_goal_id, bool) or raw_goal_id is None:
            raise TypeError("goal_id must be an integer")
        goal_id = int(raw_goal_id)
    except (TypeError, ValueError):
        return _bad("goal_id must be an integer", department_slug=slug)

    rationale = str(tool_input.get("rationale", "")).strip()
    if not rationale:
        return _bad(
            "rationale is required (one sentence: why this update)",
            department_slug=slug, goal_id=goal_id,
        )

    status_in = tool_input.get("status")
    current_in = tool_input.get("current")
    if status_in is None and current_in is None:
        return _bad(
            "must supply at least one of `status` or `current`",
            department_slug=slug, goal_id=goal_id,
        )

    if status_in is not None and status_in not in _VALID_GOAL_STATUSES:
        return _bad(
            f"status must be one of {list(_VALID_GOAL_STATUSES)}; got {status_in!r}",
            department_slug=slug, goal_id=goal_id,
        )

    current_str: str | None = None
    if current_in is not None:
        try:
            current_str = str(current_in)
        except Exception:  # noqa: BLE001 - some objects raise from str()
            return _bad("`current` must be coercible to a string",
                        department_slug=slug, goal_id=goal_id)

    # ---- Cross-department id guard ----
    existing = dept_store.get_goal(goal_id)
    if existing is None:
        return _bad(f"goal {goal_id} not found",
                    department_slug=slug, goal_id=goal_id)
    if existing.department_slug != slug:
        return _bad(
            f"goal {goal_id} belongs to department "
            f"{existing.department_slug!r}, not {slug!r}",
            department_slug=slug, goal_id=goal_id,
        )

    # ---- Persist ----
    prior_status = existing.status
    prior_current = existing.current
    prior_updated_at = existing.updated_at
    now_iso = datetime.now(UTC).isoformat()

    try:
        # `update_goal` accepts an optional `last_reviewed_at` so we record
        # the chat-driven review in the same SQL transaction — single row
        # mutation, single Honcho mirror, single `updated_at` bump.
        updated = dept_store.update_goal(
            goal_id,
            status=status_in if status_in is not None else None,
            current=current_str,
            last_reviewed_at=now_iso,
        )
    except Exception as exc:
        logger.exception("update_department_goal: store.update_goal failed id=%s", goal_id)
        _audit(
            "update_department_goal", "write", False,
            f"update_department_goal FAILED id={goal_id}: {exc}",
            {"department_slug": slug, "goal_id": goal_id, "error": str(exc)[:300]},
            department=slug,
        )
        return json.dumps({"error": str(exc)})

    if not updated:
        # Shouldn't happen — we just confirmed the row exists above — but
        # surface the corner case rather than claim success.
        return _bad("update_goal returned False (row vanished mid-call?)",
                    department_slug=slug, goal_id=goal_id)

    # Invalidate the in-memory department cache so subsequent reads
    # (the next /departments fetch, the next prompt-block render) see
    # the fresh status without waiting for a TTL.
    try:
        dept_registry.invalidate()
    except Exception:  # noqa: BLE001 - cache-invalidate must not break the tool.
        logger.warning("update_department_goal: registry invalidate failed", exc_info=True)

    new_status = status_in if status_in is not None else prior_status
    summary = (
        f"update_department_goal {slug}/{goal_id}: "
        f"{prior_status}->{new_status}"
        + ("" if current_str is None else " (current updated)")
    )
    _audit(
        "update_department_goal", "write", True, summary,
        {
            "department_slug": slug,
            "goal_id": goal_id,
            "from_status": prior_status,
            "to_status": new_status,
            "prior_current": prior_current,
            "new_current": current_str,
            "prior_updated_at": prior_updated_at,
            "rationale": rationale[:280],
        },
        department=slug,
    )

    return json.dumps({
        "status": "ok",
        "department_slug": slug,
        "goal_id": goal_id,
        "from_status": prior_status,
        "to_status": new_status,
        "current_updated": current_str is not None,
    })


DEPARTMENT_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "list_department_goals": handle_list_department_goals,
    "update_department_goal": handle_update_department_goal,
}
