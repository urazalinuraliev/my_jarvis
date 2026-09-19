"""Anthropic tool definitions + handlers for the staff-onboarding framework.

Exposed to the Executive alongside the talent tools so onboarding can be driven
and inspected from chat: list/create/advance plans, list templates, complete a
task, and run the ``role_onboarding`` workflow (which generates the welcome
brief). Mirrors the shape of ``orchestrator.talent_tools``.

Registered in ``_ALL_SKILL_TOOLS`` / ``_ALL_SKILL_HANDLERS`` in
``orchestrator.executive``.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openexecutive.audit import log_event as audit_log
from openexecutive.staff_onboarding import service, store
from openexecutive.staff_onboarding.models import OnboardingStatus, TaskStatus

logger = logging.getLogger(__name__)

_STATUS_VALUES = [s.value for s in OnboardingStatus]
_MAX_SHORT = 200


def _audit(tool: str, kind: str, ok: bool, summary: str, details: dict[str, Any]) -> None:
    audit_log(
        "tool_invocation", summary, actor="executive",
        details={"tool": tool, "kind": kind, "ok": ok, **details},
    )


def _err(tool: str, msg: str) -> str:
    _audit(tool, "read", False, f"{tool}: {msg}", {"error": msg[:300]})
    return json.dumps({"error": msg})


# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #

LIST_ONBOARDING_PLANS_TOOL: dict[str, Any] = {
    "name": "list_onboarding_plans",
    "description": (
        "List in-flight staff-onboarding plans (one per new hire) with a progress "
        "rollup: name, role, phase, completion %, open and overdue tasks. Use this "
        "to answer 'how is onboarding going?' or to resolve a hire's name to a "
        "plan_id before get_onboarding_plan / advance_onboarding_plan. Archived "
        "plans are omitted unless include_archived is set; pass status to narrow "
        "(e.g. status='active'), or status='completed' to see finished ones."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": _STATUS_VALUES,
                       "description": "Optional status filter (draft/active/completed/archived)."},
            "include_archived": {"type": "boolean",
                                 "description": "Include archived plans (default false)."},
        },
    },
}

GET_ONBOARDING_PLAN_TOOL: dict[str, Any] = {
    "name": "get_onboarding_plan",
    "description": (
        "Get one onboarding plan in full: the hire, role, phase, completion %, the "
        "generated welcome brief (if any), and every checklist task with its phase, "
        "owner, due date, and status. Call list_onboarding_plans first if you need "
        "the plan_id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"plan_id": {"type": "integer"}},
        "required": ["plan_id"],
    },
}

LIST_ONBOARDING_TEMPLATES_TOOL: dict[str, Any] = {
    "name": "list_onboarding_templates",
    "description": (
        "List the reusable onboarding templates (role/department blueprints) a new "
        "plan can be instantiated from. Returns each template's name, title, "
        "department, task count, and ramp length."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

CREATE_ONBOARDING_PLAN_TOOL: dict[str, Any] = {
    "name": "create_onboarding_plan",
    "description": (
        "Create an onboarding plan for a new hire, optionally instantiating tasks "
        "from a template (use list_onboarding_templates to pick one). Pass "
        "person_id once the hire exists on the roster (that's what later unlocks "
        "delivery + ramp). The plan starts in 'draft'. After creating, call "
        "start_onboarding to generate the welcome brief."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "New hire's name."},
            "start_date": {"type": "string", "description": "Start date, ISO YYYY-MM-DD."},
            "role": {"type": "string", "description": "Role/title, e.g. 'Fractional CFO'."},
            "template_name": {"type": "string",
                              "description": "Optional template to instantiate tasks from."},
            "person_id": {"type": "integer", "description": "Roster person id, if hired."},
            "manager_person_id": {"type": "integer"},
            "buddy_person_id": {"type": "integer"},
            "engagement_id": {"type": "integer",
                              "description": "Talent engagement this hire came from, if any."},
            "candidate_id": {"type": "integer",
                             "description": "Talent candidate this hire came from, if any."},
        },
        "required": ["full_name", "start_date"],
    },
}

COMPLETE_ONBOARDING_TASK_TOOL: dict[str, Any] = {
    "name": "complete_onboarding_task",
    "description": (
        "Mark an onboarding checklist task done (or set another status). Use the "
        "task_id from get_onboarding_plan. status defaults to 'done'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "status": {"type": "string", "enum": [s.value for s in TaskStatus],
                       "description": "Defaults to 'done'."},
            "completed_by_person_id": {"type": "integer"},
        },
        "required": ["task_id"],
    },
}

ADVANCE_ONBOARDING_PLAN_TOOL: dict[str, Any] = {
    "name": "advance_onboarding_plan",
    "description": (
        "Advance a plan to its next phase (pre_start → week_1 → day_30 → day_60 → "
        "day_90). No-op if already at the final phase."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"plan_id": {"type": "integer"}},
        "required": ["plan_id"],
    },
}

ACTIVATE_ONBOARDING_PLAN_TOOL: dict[str, Any] = {
    "name": "activate_onboarding_plan",
    "description": (
        "Activate a draft onboarding plan: starts the daily ramp drip, posts a "
        "welcome notice to the hire's department channel (if one is configured), "
        "DMs intro-1:1 nudges to the manager and buddy, and schedules the day "
        "7/30/60/90 check-ins. The ramp/check-ins only fire once the plan has a "
        "roster person_id. Generate the brief first with start_onboarding. "
        "Idempotent — safe to call once per plan."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"plan_id": {"type": "integer"}},
        "required": ["plan_id"],
    },
}

START_ONBOARDING_TOOL: dict[str, Any] = {
    "name": "start_onboarding",
    "description": (
        "Generate the role-tailored welcome brief (and optional daily ramp drip) "
        "for a hire by running the role_onboarding workflow to completion. Pass a "
        "plan_id to generate for and save onto an existing plan, OR full_name + "
        "role for an ad-hoc brief. Returns the brief Markdown."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer"},
            "full_name": {"type": "string"},
            "role": {"type": "string"},
            "function": {"type": "string",
                         "description": "engineering/sales/finance/… — picks the lead specialist."},
            "ramp_days": {"type": "integer",
                          "description": "Daily ramp messages to generate (omit to use template)."},
        },
    },
}

ONBOARDING_TOOLS: list[dict[str, Any]] = [
    LIST_ONBOARDING_PLANS_TOOL,
    GET_ONBOARDING_PLAN_TOOL,
    LIST_ONBOARDING_TEMPLATES_TOOL,
    CREATE_ONBOARDING_PLAN_TOOL,
    COMPLETE_ONBOARDING_TASK_TOOL,
    ADVANCE_ONBOARDING_PLAN_TOOL,
    ACTIVATE_ONBOARDING_PLAN_TOOL,
    START_ONBOARDING_TOOL,
]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


async def handle_list_onboarding_plans(tool_input: dict[str, Any]) -> str:
    status_raw = tool_input.get("status")
    status = None
    if status_raw is not None:
        try:
            status = OnboardingStatus(str(status_raw))
        except ValueError:
            return _err("list_onboarding_plans", f"invalid status: {status_raw!r}")
    include_archived = bool(tool_input.get("include_archived", False))
    try:
        plans = store.list_plans(status=status, include_archived=include_archived)
    except Exception as exc:
        logger.exception("list_onboarding_plans: failed")
        return _err("list_onboarding_plans", str(exc))
    out = [
        {
            "plan_id": p.id, "full_name": p.full_name, "role": p.role,
            "status": p.status.value, "current_phase": p.current_phase.value,
            "completion_pct": p.completion_pct, "start_date": p.start_date,
        }
        for p in plans
    ]
    return json.dumps({"status": "ok", "plans": out})


async def handle_get_onboarding_plan(tool_input: dict[str, Any]) -> str:
    try:
        plan_id = int(tool_input["plan_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("get_onboarding_plan", f"bad arguments: {exc}")
    plan = store.get_plan(plan_id)
    if plan is None:
        return json.dumps({"status": "not_found", "plan_id": plan_id})
    return json.dumps({"status": "ok", "plan": plan.model_dump()})


async def handle_list_onboarding_templates(tool_input: dict[str, Any]) -> str:
    try:
        templates = store.list_templates(active_only=True)
    except Exception as exc:
        logger.exception("list_onboarding_templates: failed")
        return _err("list_onboarding_templates", str(exc))
    out = [
        {
            "name": t.name, "title": t.title, "department": t.department,
            "task_count": len(t.task_specs), "ramp_days": t.ramp_days,
        }
        for t in templates
    ]
    return json.dumps({"status": "ok", "templates": out})


def _opt_int(tool_input: dict[str, Any], key: str) -> int | None:
    """Coerce an optional integer arg. Absent/blank → None; a present but
    non-integer value raises ValueError so the handler can surface an error
    rather than silently dropping (e.g.) a person_id and reporting success."""
    val = tool_input.get(key)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer, got {val!r}") from exc


async def handle_create_onboarding_plan(tool_input: dict[str, Any]) -> str:
    full_name = str(tool_input.get("full_name", "")).strip()
    start_date = str(tool_input.get("start_date", "")).strip()
    if not full_name or not start_date:
        return _err("create_onboarding_plan", "full_name and start_date are required")
    role = str(tool_input.get("role", "") or "")
    if len(full_name) > _MAX_SHORT or len(role) > _MAX_SHORT or len(start_date) > _MAX_SHORT:
        return _err("create_onboarding_plan", "full_name/role/start_date too long")

    template = None
    template_name = str(tool_input.get("template_name", "") or "").strip()
    if template_name:
        template = store.get_template(template_name)
        if template is None:
            return _err("create_onboarding_plan", f"unknown template {template_name!r}")

    try:
        plan_id = service.instantiate_plan(
            full_name=full_name,
            start_date=start_date,
            role=role,
            template=template,
            person_id=_opt_int(tool_input, "person_id"),
            manager_person_id=_opt_int(tool_input, "manager_person_id"),
            buddy_person_id=_opt_int(tool_input, "buddy_person_id"),
            engagement_id=_opt_int(tool_input, "engagement_id"),
            candidate_id=_opt_int(tool_input, "candidate_id"),
        )
        plan = store.get_plan(plan_id)
    except Exception as exc:
        logger.exception("create_onboarding_plan: failed")
        return _err("create_onboarding_plan", str(exc))
    if plan is None:
        return _err("create_onboarding_plan", f"created plan {plan_id} but could not reload it")
    _audit("create_onboarding_plan", "write", True,
           f"create_onboarding_plan {plan_id} {full_name}",
           {"plan_id": plan_id, "full_name": full_name, "template": template_name})
    return json.dumps({"status": "ok", "plan": plan.model_dump()})


async def handle_complete_onboarding_task(tool_input: dict[str, Any]) -> str:
    try:
        task_id = int(tool_input["task_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("complete_onboarding_task", f"bad arguments: {exc}")
    status = TaskStatus.DONE
    status_raw = tool_input.get("status")
    if status_raw is not None:
        try:
            status = TaskStatus(str(status_raw))
        except ValueError:
            return _err("complete_onboarding_task", f"invalid status: {status_raw!r}")
    if store.get_task(task_id) is None:
        return json.dumps({"status": "not_found", "task_id": task_id})
    try:
        completed_by = _opt_int(tool_input, "completed_by_person_id")
    except ValueError as exc:
        return _err("complete_onboarding_task", str(exc))
    store.set_task_status(task_id, status, completed_by_person_id=completed_by)
    _audit("complete_onboarding_task", "write", True,
           f"complete_onboarding_task {task_id} → {status.value}",
           {"task_id": task_id, "status": status.value})
    task = store.get_task(task_id)
    return json.dumps({"status": "ok", "task": task.model_dump() if task else None})


async def handle_advance_onboarding_plan(tool_input: dict[str, Any]) -> str:
    try:
        plan_id = int(tool_input["plan_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("advance_onboarding_plan", f"bad arguments: {exc}")
    if store.get_plan(plan_id) is None:
        return json.dumps({"status": "not_found", "plan_id": plan_id})
    new_phase = service.advance_phase(plan_id)
    _audit("advance_onboarding_plan", "write", True,
           f"advance_onboarding_plan {plan_id} → {new_phase}",
           {"plan_id": plan_id, "new_phase": new_phase.value if new_phase else None})
    return json.dumps({
        "status": "ok", "plan_id": plan_id,
        "new_phase": new_phase.value if new_phase else None,
        "note": "already at final phase" if new_phase is None else "",
    })


async def handle_activate_onboarding_plan(tool_input: dict[str, Any]) -> str:
    try:
        plan_id = int(tool_input["plan_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("activate_onboarding_plan", f"bad arguments: {exc}")
    if store.get_plan(plan_id) is None:
        return json.dumps({"status": "not_found", "plan_id": plan_id})
    try:
        service.activate_plan(plan_id)
    except Exception as exc:
        logger.exception("activate_onboarding_plan: failed")
        return _err("activate_onboarding_plan", str(exc))
    _audit("activate_onboarding_plan", "write", True,
           f"activate_onboarding_plan {plan_id}", {"plan_id": plan_id})
    plan = store.get_plan(plan_id)
    return json.dumps({"status": "ok", "plan": plan.model_dump() if plan else None})


async def handle_start_onboarding(tool_input: dict[str, Any]) -> str:
    from openexecutive.config import get_settings
    from openexecutive.knowledge.store import ChromaDBStore
    from openexecutive.workflows import WORKFLOW_REGISTRY
    from openexecutive.workflows.persistence import complete_run, create_run, fail_run

    workflow = WORKFLOW_REGISTRY["role_onboarding"]
    raw = {k: tool_input.get(k) for k in ("plan_id", "full_name", "role", "function", "ramp_days")
           if tool_input.get(k) is not None}
    try:
        wf_inputs = workflow.input_model().model_validate(raw)
    except Exception as exc:
        return _err("start_onboarding", f"invalid inputs: {exc}")

    run_id = str(uuid.uuid4())
    try:
        create_run(run_id, "role_onboarding", f"{workflow.title} (chat-tool fire)",
                   wf_inputs.model_dump())
    except Exception:
        logger.exception("start_onboarding: create_run failed")

    artifact = ""
    last_error = ""
    chroma = ChromaDBStore(persist_directory=get_settings().vector_store_path)
    try:
        async for event in workflow.run(inputs=wf_inputs, store=chroma):
            if event.type == "artifact" and event.content:
                artifact = event.content
            elif event.type == "error" and event.message:
                last_error = event.message
    except Exception as exc:
        logger.exception("start_onboarding: workflow.run crashed")
        last_error = str(exc)[:200]

    import contextlib
    if last_error:
        with contextlib.suppress(Exception):
            fail_run(run_id, last_error)
        return _err("start_onboarding", last_error)
    with contextlib.suppress(Exception):
        complete_run(run_id, artifact or "(no artifact)")
    _audit("start_onboarding", "write", True, "start_onboarding generated brief",
           {"plan_id": tool_input.get("plan_id"), "chars": len(artifact)})
    return json.dumps({"status": "ok", "artifact": artifact})


ONBOARDING_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "list_onboarding_plans": handle_list_onboarding_plans,
    "get_onboarding_plan": handle_get_onboarding_plan,
    "list_onboarding_templates": handle_list_onboarding_templates,
    "create_onboarding_plan": handle_create_onboarding_plan,
    "complete_onboarding_task": handle_complete_onboarding_task,
    "advance_onboarding_plan": handle_advance_onboarding_plan,
    "activate_onboarding_plan": handle_activate_onboarding_plan,
    "start_onboarding": handle_start_onboarding,
}


__all__ = ["ONBOARDING_TOOLS", "ONBOARDING_TOOL_HANDLERS"]
