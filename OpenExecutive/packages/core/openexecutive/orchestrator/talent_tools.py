"""Anthropic tool definitions + handlers for the talent / executive-search vertical.

The ``TalentAgent`` specialist can *advise* on screening and sourcing from RAG,
but until now the Executive had no way to read the live pipeline (engagements,
candidates, matches) or start the talent workflows from a chat turn — so the
``/talent`` UI and the conversation were two disconnected worlds.

These tools close that gap. They sit alongside ``list_people`` / ``create_alert``
/ ``run_executive_research`` in the Executive's main tool loop:

- read tools (``list_engagements`` / ``list_candidates`` / ``get_candidate`` /
  ``match_candidates``) expose the live pipeline,
- ``set_candidate_stage`` is a light, reversible write that keeps the pipeline
  truthful from chat,
- ``create_engagement`` / ``create_candidate`` build the pipeline from chat —
  they mirror the ``/talent`` API routes (the same ``upsert_*`` store calls), so
  a search can be opened in conversation. ``create_engagement`` opens a role
  we're hiring for in this company (no external client); ``create_candidate``
  re-indexes the new person into the talent graph just like the API route does.
- ``start_talent_workflow`` fires one of the existing draft-and-approve talent
  workflows to completion (mirroring ``run_executive_research``), so the
  Executive can act on a search without an HTTP round-trip.

The ``/talent`` UI remains the home for heavier editing (updates, soft-archive)
and bulk work; chat covers create + the lightweight pipeline moves above.
JSON-in / JSON-out, matching the other orchestrator tools.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openexecutive.audit import log_event as audit_log
from openexecutive.talent.models import CandidateStage, EngagementStatus, OfferStatus

logger = logging.getLogger(__name__)

_STAGE_VALUES = [s.value for s in CandidateStage]
_ENGAGEMENT_STATUS_VALUES = [s.value for s in EngagementStatus]
_OFFER_STATUS_VALUES = [s.value for s in OfferStatus]

# match_candidates result-count bounds: the model's `limit` is clamped to
# [1, _MAX_MATCH_LIMIT]; _DEFAULT_MATCH_LIMIT applies when it omits one.
_DEFAULT_MATCH_LIMIT = 10
_MAX_MATCH_LIMIT = 50

# The talent workflows reachable from chat. ``exec_search_brief`` is generative
# (no existing candidate/engagement required); the rest operate on a candidate
# already in the pipeline. All are short and draft-and-approve. Only
# ``offer_approval`` pauses on a wait-for-human gate — the handler checkpoints
# the run and reports ``awaiting_human`` (mirroring ``run_workflow``); the
# others run to completion inside the tool handler.
_TALENT_WORKFLOWS = [
    "candidate_screen",
    "candidate_outreach",
    "interview_coordination",
    "reference_check",
    "exec_search_brief",
    "offer_approval",
    "new_hire_onboarding",
]


# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #

LIST_ENGAGEMENTS_TOOL: dict[str, Any] = {
    "name": "list_engagements",
    "description": (
        "List the active executive-search engagements (open / on-hold) with a "
        "pipeline rollup per search: client name, role, status, candidate count, "
        "how many need screening (leads), how many offers are out, and how many "
        "candidates have stalled. Use this to answer 'how are our searches "
        "going?' or to resolve a client/role to an engagement_id before calling "
        "list_candidates, match_candidates, or start_talent_workflow. Filled and "
        "cancelled searches are omitted."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


LIST_CANDIDATES_TOOL: dict[str, Any] = {
    "name": "list_candidates",
    "description": (
        "List the candidates in one engagement's pipeline, newest id last. "
        "Optionally filter to a single stage. Returns a compact JSON list with "
        "each candidate's id, name, current title/company, stage, and fit_score. "
        "Call list_engagements first if you need the engagement_id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "engagement_id": {
                "type": "integer",
                "description": "The engagement (search) whose candidates to list.",
            },
            "stage": {
                "type": "string",
                "enum": _STAGE_VALUES,
                "description": "Optional pipeline stage to filter to.",
            },
        },
        "required": ["engagement_id"],
    },
}


GET_CANDIDATE_TOOL: dict[str, Any] = {
    "name": "get_candidate",
    "description": (
        "Fetch full detail for one candidate by id, including fit_score and the "
        "screening_summary produced by the candidate_screen workflow. Use before "
        "discussing a specific candidate or starting a workflow for them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer", "description": "Id of the candidate."},
        },
        "required": ["candidate_id"],
    },
}


MATCH_CANDIDATES_TOOL: dict[str, Any] = {
    "name": "match_candidates",
    "description": (
        "Rank the candidate pool against an engagement's role and must-haves "
        "using the semantic talent graph. Returns up to `limit` candidates best "
        "first, each with a 0-1 match score, current stage, name, and title. Use "
        "when the principal asks 'who's the best fit for X' or to surface "
        "candidates worth advancing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "engagement_id": {
                "type": "integer",
                "description": "The engagement to rank candidates against.",
            },
            "limit": {
                "type": "integer",
                "description": "Max matches to return (default 10).",
            },
        },
        "required": ["engagement_id"],
    },
}


SET_CANDIDATE_STAGE_TOOL: dict[str, Any] = {
    "name": "set_candidate_stage",
    "description": (
        "Move a candidate to a pipeline stage (lead → screened → interviewed → "
        "offer → placed, or the rejected off-ramp). A light, reversible update "
        "that keeps the pipeline truthful when the principal tells you a "
        "candidate advanced or dropped out. For a full screen with a fit score, "
        "use start_talent_workflow('candidate_screen') instead — do not set "
        "'screened' by hand to fake a score."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer", "description": "Id of the candidate to move."},
            "stage": {
                "type": "string",
                "enum": _STAGE_VALUES,
                "description": "The stage to move the candidate to.",
            },
        },
        "required": ["candidate_id", "stage"],
    },
}


START_TALENT_WORKFLOW_TOOL: dict[str, Any] = {
    "name": "start_talent_workflow",
    "description": (
        "Run one of the talent workflows to completion and return its artifact. "
        "All are draft-and-approve — they schedule reminders/drafts to the search "
        "principal and NEVER contact a candidate or reference directly.\n"
        "Workflows and their `inputs`:\n"
        " - candidate_screen: {engagement_id:int, candidate_id:int} — screen a "
        "candidate against the role and persist a fit score.\n"
        " - candidate_outreach: {candidate_id:int, follow_up_count?:int(0-5), "
        "follow_up_interval_days?:int(1-30), angle?:str} — draft a first touch + "
        "follow-up sequence.\n"
        " - interview_coordination: {candidate_id:int, num_rounds?:int(1-7), "
        "notes?:str} — design the interview loop.\n"
        " - reference_check: {candidate_id:int, reference_count?:int(1-5), "
        "reference_notes?:str} — draft a reference-check rubric.\n"
        " - exec_search_brief: {role_title:str, function:str, business_context:str, "
        "year_one_outcomes:str, non_negotiables?:str} — generate a hiring brief "
        "for a NEW search (no candidate needed).\n"
        " - offer_approval: {candidate_id:int, comp_notes?:str, angle?:str} — "
        "draft the offer package and request hiring sign-off; the run PAUSES "
        "until the approver replies (returns awaiting_human). After approval, "
        "use extend_offer.\n"
        " - new_hire_onboarding: {candidate_id:int, start_date?:str(ISO date), "
        "focus_notes?:str} — placed-candidate handoff: roster Person + 30/60/90 "
        "plan + milestone check-in reminders.\n"
        "Resolve ids with list_engagements / list_candidates first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "workflow": {
                "type": "string",
                "enum": _TALENT_WORKFLOWS,
                "description": "Which talent workflow to run.",
            },
            "inputs": {
                "type": "object",
                "description": "The workflow's input fields (see the per-workflow list above).",
            },
        },
        "required": ["workflow", "inputs"],
    },
}


CREATE_ENGAGEMENT_TOOL: dict[str, Any] = {
    "name": "create_engagement",
    "description": (
        "Open a new search — a role we're hiring for in this company. Only "
        "role_title is required; `department` is an optional in-house grouping "
        "(e.g. 'Drilling'). Use list_engagements to see existing searches first "
        "so you don't open a duplicate."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "role_title": {"type": "string", "description": "The role being searched for."},
            "department": {
                "type": "string",
                "description": "Optional in-house team/department this role sits in.",
            },
            "status": {
                "type": "string",
                "enum": _ENGAGEMENT_STATUS_VALUES,
                "description": "Engagement status, optional (defaults to open).",
            },
            "location": {"type": "string", "description": "Role location, optional."},
            "comp_band": {"type": "string", "description": "Compensation band, optional."},
            "must_haves": {"type": "string", "description": "Must-have requirements, optional."},
            "description": {"type": "string", "description": "Role description, optional."},
        },
        "required": ["role_title"],
    },
}


CREATE_CANDIDATE_TOOL: dict[str, Any] = {
    "name": "create_candidate",
    "description": (
        "Add a candidate to an EXISTING engagement's pipeline. You must pass a "
        "valid engagement_id (resolve with list_engagements; returns not_found "
        "for an unknown one). Only engagement_id and full_name are required; the "
        "candidate is indexed for semantic matching automatically. Do NOT set a "
        "fit score here — run start_talent_workflow('candidate_screen') for that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "engagement_id": {"type": "integer", "description": "Id of the existing engagement."},
            "full_name": {"type": "string", "description": "Candidate's full name (required)."},
            "current_title": {"type": "string", "description": "Current title, optional."},
            "current_company": {"type": "string", "description": "Current company, optional."},
            "location": {"type": "string", "description": "Location, optional."},
            "email": {"type": "string", "description": "Email, optional."},
            "linkedin_url": {"type": "string", "description": "LinkedIn URL, optional."},
            "source": {"type": "string", "description": "How sourced (e.g. referral), optional."},
            "stage": {
                "type": "string",
                "enum": _STAGE_VALUES,
                "description": "Starting pipeline stage, optional (defaults to lead).",
            },
            "notes": {"type": "string", "description": "Free-text notes, optional."},
        },
        "required": ["engagement_id", "full_name"],
    },
}


LIST_OFFERS_TOOL: dict[str, Any] = {
    "name": "list_offers",
    "description": (
        "List offers, optionally filtered by candidate, engagement, and/or "
        "status (draft / pending_approval / extended / accepted / declined / "
        "expired / rescinded). Returns each offer's id, candidate, status, comp "
        "summary, and expiry. Use to answer 'where is the offer to X?' or "
        "before extend_offer / record_offer_decision."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer", "description": "Filter to one candidate."},
            "engagement_id": {"type": "integer", "description": "Filter to one engagement."},
            "status": {
                "type": "string",
                "enum": _OFFER_STATUS_VALUES,
                "description": "Filter to one offer status.",
            },
        },
    },
}


CREATE_OFFER_TOOL: dict[str, Any] = {
    "name": "create_offer",
    "description": (
        "Record a draft offer for a candidate with terms the principal "
        "dictated. One open offer per candidate. For a fully drafted package "
        "with hiring sign-off, run start_talent_workflow('offer_approval') "
        "instead — this tool is the manual path when the principal already "
        "knows the terms. The offer starts as a draft; use extend_offer once "
        "the principal actually sends it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer", "description": "The candidate the offer is for."},
            "comp_summary": {
                "type": "string",
                "description": "The terms in brief (base, equity, sign-on, start date…).",
            },
            "note": {"type": "string", "description": "Optional context note."},
        },
        "required": ["candidate_id", "comp_summary"],
    },
}


EXTEND_OFFER_TOOL: dict[str, Any] = {
    "name": "extend_offer",
    "description": (
        "Mark an offer as extended — the principal sent it to the candidate "
        "themselves (OE NEVER sends offers to candidates) — and schedule expiry "
        "reminders to the principal. Checks the recorded hiring sign-off: a "
        "rejection blocks this; a pending/absent sign-off proceeds on the "
        "principal's explicit instruction and is flagged in the response. "
        "Expiry defaults to 7 days out."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "offer_id": {"type": "integer", "description": "The offer to mark extended."},
            "expires_in_days": {
                "type": "integer",
                "description": "Days until the offer expires (1-60, default 7).",
            },
            "expires_at": {
                "type": "string",
                "description": "Explicit ISO expiry timestamp (overrides expires_in_days).",
            },
            "note": {"type": "string", "description": "Optional context note."},
        },
        "required": ["offer_id"],
    },
}


RECORD_OFFER_DECISION_TOOL: dict[str, Any] = {
    "name": "record_offer_decision",
    "description": (
        "Record the outcome of an extended offer: accepted, declined, expired, "
        "or rescinded (rescind also works on a draft/pending offer). Cancels "
        "the offer's pending expiry reminders. 'accepted' also moves the "
        "candidate to placed and the engagement to filled, and the response "
        "will suggest running new_hire_onboarding. declined/expired/rescinded "
        "leave the candidate's stage for the principal to decide."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "offer_id": {"type": "integer", "description": "The offer to decide."},
            "decision": {
                "type": "string",
                "enum": ["accepted", "declined", "expired", "rescinded"],
                "description": "The outcome.",
            },
            "note": {"type": "string", "description": "Optional context (e.g. why declined)."},
        },
        "required": ["offer_id", "decision"],
    },
}


TALENT_TOOLS: list[dict[str, Any]] = [
    LIST_ENGAGEMENTS_TOOL,
    LIST_CANDIDATES_TOOL,
    GET_CANDIDATE_TOOL,
    MATCH_CANDIDATES_TOOL,
    CREATE_ENGAGEMENT_TOOL,
    CREATE_CANDIDATE_TOOL,
    SET_CANDIDATE_STAGE_TOOL,
    START_TALENT_WORKFLOW_TOOL,
    LIST_OFFERS_TOOL,
    CREATE_OFFER_TOOL,
    EXTEND_OFFER_TOOL,
    RECORD_OFFER_DECISION_TOOL,
]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def _audit(tool: str, kind: str, ok: bool, summary: str, details: dict[str, Any]) -> None:
    audit_log(
        "tool_invocation",
        summary,
        actor="executive",
        details={"tool": tool, "kind": kind, "ok": ok, **details},
    )


def _err(tool: str, msg: str) -> str:
    _audit(tool, "read", False, f"{tool}: {msg}", {"error": msg[:300]})
    return json.dumps({"error": msg})


# Text-field length caps for the chat create tools, mirroring the Pydantic
# bounds the /talent API routes enforce (api/routes/talent.py) — chat is just
# another caller, so it must not be able to persist (and then embed) unbounded
# free text that the HTTP path rejects.
_MAX_SHORT = 200  # names, titles, locations, comp band, source
_MAX_MEDIUM = 4000  # client notes
_MAX_LONG = 8000  # role must-haves / descriptions, candidate notes


def _length_error(tool: str, checks: list[tuple[str, str, int]]) -> str | None:
    """Return an `_err` JSON string for the first over-length field, else None."""
    for label, value, limit in checks:
        if len(value) > limit:
            return _err(tool, f"{label} too long ({len(value)} > {limit} chars)")
    return None


def _candidate_summary(cand: Any) -> dict[str, Any]:
    return {
        "candidate_id": cand.id,
        "engagement_id": cand.engagement_id,
        "full_name": cand.full_name,
        "current_title": cand.current_title,
        "current_company": cand.current_company,
        "stage": cand.stage.value,
        "fit_score": cand.fit_score,
    }


async def handle_list_engagements(tool_input: dict[str, Any]) -> str:
    # Reuse the shared briefing rollup so chat and /today never disagree on
    # pipeline state.
    from openexecutive.briefing.talent_digest import build_talent_brief_items

    try:
        items = build_talent_brief_items()
    except Exception as exc:
        logger.exception("list_engagements: failed")
        return _err("list_engagements", str(exc))

    out = [it.model_dump() for it in items]
    _audit(
        "list_engagements", "read", True,
        f"list_engagements returned {len(out)}",
        {"count": len(out)},
    )
    return json.dumps({"engagements": out, "count": len(out)})


async def handle_list_candidates(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    try:
        engagement_id = int(tool_input["engagement_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("list_candidates", f"bad arguments: {exc}")

    stage: CandidateStage | None = None
    stage_raw = tool_input.get("stage")
    if stage_raw is not None:
        try:
            stage = CandidateStage(str(stage_raw))
        except ValueError:
            return _err("list_candidates", f"invalid stage: {stage_raw!r}")

    try:
        candidates = talent_store.list_candidates(engagement_id=engagement_id, stage=stage)
    except Exception as exc:
        logger.exception("list_candidates: failed")
        return _err("list_candidates", str(exc))

    out = [_candidate_summary(c) for c in candidates]
    _audit(
        "list_candidates", "read", True,
        f"list_candidates engagement={engagement_id} returned {len(out)}",
        {"engagement_id": engagement_id, "count": len(out), "stage": stage.value if stage else None},
    )
    return json.dumps({"candidates": out, "count": len(out)})


async def handle_get_candidate(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    try:
        candidate_id = int(tool_input["candidate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("get_candidate", f"bad arguments: {exc}")

    try:
        cand = talent_store.get_candidate(candidate_id)
    except Exception as exc:
        logger.exception("get_candidate: failed")
        return _err("get_candidate", str(exc))

    if cand is None:
        _audit("get_candidate", "read", False, f"get_candidate {candidate_id} not found",
               {"candidate_id": candidate_id})
        return json.dumps({"status": "not_found", "candidate_id": candidate_id})

    _audit("get_candidate", "read", True, f"get_candidate {candidate_id}",
           {"candidate_id": candidate_id})
    return json.dumps({"candidate": cand.model_dump()})


async def handle_match_candidates(tool_input: dict[str, Any]) -> str:
    from openexecutive.config import get_settings
    from openexecutive.knowledge.store import ChromaDBStore
    from openexecutive.talent import graph as talent_graph
    from openexecutive.talent import store as talent_store

    try:
        engagement_id = int(tool_input["engagement_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("match_candidates", f"bad arguments: {exc}")

    limit_raw = tool_input.get("limit", _DEFAULT_MATCH_LIMIT)
    try:
        limit = max(1, min(int(limit_raw), _MAX_MATCH_LIMIT))
    except (TypeError, ValueError):
        return _err("match_candidates", "limit must be an integer")

    try:
        engagement = talent_store.get_engagement(engagement_id)
    except Exception as exc:
        logger.exception("match_candidates: get_engagement failed")
        return _err("match_candidates", str(exc))
    if engagement is None:
        return json.dumps({"status": "not_found", "engagement_id": engagement_id})

    try:
        store = ChromaDBStore(persist_directory=get_settings().vector_store_path)
        matches = talent_graph.match_candidates_for_engagement(engagement, store, limit=limit)
    except Exception as exc:
        logger.exception("match_candidates: graph query failed")
        return _err("match_candidates", str(exc))

    # Enrich each match with the candidate's name/title so the Executive can
    # talk about people, not bare ids.
    enriched: list[dict[str, Any]] = []
    for m in matches:
        cid = m.get("candidate_id")
        name = title = None
        if cid is not None:
            try:
                cand = talent_store.get_candidate(int(cid))
            except Exception:
                cand = None
            if cand is not None:
                name, title = cand.full_name, cand.current_title
        enriched.append({**m, "full_name": name, "current_title": title})

    _audit(
        "match_candidates", "read", True,
        f"match_candidates engagement={engagement_id} returned {len(enriched)}",
        {"engagement_id": engagement_id, "count": len(enriched)},
    )
    return json.dumps({"engagement_id": engagement_id, "matches": enriched, "count": len(enriched)})


async def handle_set_candidate_stage(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    try:
        candidate_id = int(tool_input["candidate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("set_candidate_stage", f"bad arguments: {exc}")

    try:
        stage = CandidateStage(str(tool_input["stage"]))
    except (KeyError, ValueError) as exc:
        return _err("set_candidate_stage", f"invalid or missing stage: {exc}")

    existing = talent_store.get_candidate(candidate_id)
    if existing is None:
        _audit("set_candidate_stage", "write", False,
               f"set_candidate_stage {candidate_id} not found", {"candidate_id": candidate_id})
        return json.dumps({"status": "not_found", "candidate_id": candidate_id})

    try:
        changed = talent_store.set_candidate_stage(candidate_id, stage)
    except Exception as exc:
        logger.exception("set_candidate_stage: failed")
        return _err("set_candidate_stage", str(exc))

    _audit(
        "set_candidate_stage", "write", True,
        f"set_candidate_stage {candidate_id} -> {stage.value}",
        {"candidate_id": candidate_id, "stage": stage.value, "changed": changed},
    )
    result: dict[str, Any] = {
        "status": "ok",
        "candidate_id": candidate_id,
        "stage": stage.value,
        "changed": changed,
    }
    # Suggest-on-placed: a placed candidate is a hire — prompt the Executive to
    # chain the hire-loop steps. A suggestion only, never an auto-fire, and OE
    # still never messages the candidate directly. The two onboarding surfaces
    # compose: new_hire_onboarding records the offer outcome's roster Person
    # (which staff-onboarding delivery/ramp needs) + principal 30/60/90
    # check-ins; create_onboarding_plan/start_onboarding add the structured
    # task plan, welcome brief, and ramp drip.
    if stage == CandidateStage.PLACED:
        result["onboarding_suggestion"] = (
            f"{existing.full_name} is placed — if this reflects an accepted "
            "offer, record it with record_offer_decision first. Then run "
            "start_talent_workflow('new_hire_onboarding') to add them to the "
            "People roster and schedule 30/60/90 check-ins. After that, call "
            f"create_onboarding_plan(full_name={existing.full_name!r}, "
            f"candidate_id={candidate_id}, engagement_id={existing.engagement_id}, "
            "person_id=<from new_hire_onboarding>, template_name=<role-appropriate>) "
            "and start_onboarding to generate the welcome brief and enable "
            "delivery and the ramp drip."
        )
    return json.dumps(result)


async def handle_start_talent_workflow(tool_input: dict[str, Any]) -> str:
    from datetime import UTC, datetime, timedelta

    from openexecutive.config import get_settings
    from openexecutive.knowledge.store import ChromaDBStore
    from openexecutive.workflows import WORKFLOW_REGISTRY
    from openexecutive.workflows.persistence import (
        complete_run,
        create_run,
        fail_run,
        save_checkpoint,
    )
    from openexecutive.workflows.wait_for_human import WaitForHumanEvent

    name = str(tool_input.get("workflow", "")).strip()
    if name not in _TALENT_WORKFLOWS:
        return _err(
            "start_talent_workflow",
            f"workflow must be one of {_TALENT_WORKFLOWS}, got {name!r}",
        )

    raw_inputs = tool_input.get("inputs")
    if not isinstance(raw_inputs, dict):
        return _err("start_talent_workflow", "inputs must be an object")

    workflow = WORKFLOW_REGISTRY[name]
    input_cls = workflow.input_model()
    try:
        wf_inputs = input_cls.model_validate(raw_inputs)
    except Exception as exc:
        # Surface the validation error so the model can correct its inputs.
        return _err("start_talent_workflow", f"invalid inputs for {name}: {exc}")

    run_id = str(uuid.uuid4())
    try:
        create_run(run_id, name, f"{workflow.title} (chat-tool fire)", wf_inputs.model_dump())
    except Exception:
        logger.exception("start_talent_workflow: create_run failed")

    artifact = ""
    last_error = ""
    awaiting: dict[str, Any] | None = None
    store = ChromaDBStore(persist_directory=get_settings().vector_store_path)
    try:
        async for event in workflow.run(inputs=wf_inputs, store=store):
            # An approval-gate step yields a WaitForHumanEvent (not a
            # WorkflowEvent): checkpoint the run and stop, mirroring
            # handle_run_workflow. The resumer applies the timeout policy and
            # the inbound resolver records the human's reply.
            if isinstance(event, WaitForHumanEvent):
                until = datetime.now(UTC) + timedelta(hours=event.timeout_hours)
                save_checkpoint(
                    run_id=run_id,
                    state_json=event.model_dump_json(),
                    awaiting_person_id=event.person_id,
                    awaiting_until=until,
                )
                awaiting = {
                    "person_id": event.person_id,
                    "question": event.question,
                    "awaiting_until": until.isoformat(),
                }
                break
            if event.type == "artifact" and event.content:
                artifact = event.content
            elif event.type == "error" and event.message:
                last_error = event.message
    except Exception as exc:
        logger.exception("start_talent_workflow: workflow.run crashed")
        last_error = str(exc)[:200]

    if awaiting is not None:
        _audit("start_talent_workflow", "write", True,
               f"start_talent_workflow {name} awaiting_human run_id={run_id}",
               {"workflow": name, "run_id": run_id, "status": "awaiting_human"})
        return json.dumps({
            "status": "awaiting_human",
            "workflow": name,
            "run_id": run_id,
            **awaiting,
            "artifact": artifact,
            "presentation_hint": (
                "This workflow paused for sign-off from the named person. Tell "
                "the principal it's waiting on them; do not re-run it."
            ),
        })

    if last_error:
        import contextlib
        with contextlib.suppress(Exception):
            fail_run(run_id, last_error)
        _audit("start_talent_workflow", "write", False,
               f"start_talent_workflow {name} FAILED — {last_error}",
               {"workflow": name, "error": last_error, "run_id": run_id})
        return json.dumps({"error": f"workflow error: {last_error}", "run_id": run_id})

    import contextlib
    with contextlib.suppress(Exception):
        complete_run(run_id, artifact or "(no artifact)")

    _audit("start_talent_workflow", "write", True,
           f"start_talent_workflow {name} ok run_id={run_id}",
           {"workflow": name, "run_id": run_id})
    return json.dumps({
        "ok": True,
        "workflow": name,
        "run_id": run_id,
        "artifact": artifact,
        "presentation_hint": (
            "The workflow already drafted its output and scheduled any "
            "reminders to the search principal. Summarise the artifact for the "
            "principal; do not re-run the workflow or contact candidates/"
            "references yourself."
        ),
    })


async def handle_create_engagement(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    role_title = str(tool_input.get("role_title", "")).strip()
    if not role_title:
        return _err("create_engagement", "role_title is required")

    status = EngagementStatus.OPEN
    status_raw = tool_input.get("status")
    if status_raw is not None:
        try:
            status = EngagementStatus(str(status_raw))
        except ValueError:
            return _err("create_engagement", f"invalid status: {status_raw!r}")

    department = str(tool_input.get("department", "") or "")
    location = str(tool_input.get("location", "") or "")
    comp_band = str(tool_input.get("comp_band", "") or "")
    must_haves = str(tool_input.get("must_haves", "") or "")
    description = str(tool_input.get("description", "") or "")
    length_err = _length_error("create_engagement", [
        ("role_title", role_title, _MAX_SHORT),
        ("department", department, _MAX_SHORT),
        ("location", location, _MAX_SHORT),
        ("comp_band", comp_band, _MAX_SHORT),
        ("must_haves", must_haves, _MAX_LONG),
        ("description", description, _MAX_LONG),
    ])
    if length_err:
        return length_err

    try:
        engagement_id = talent_store.upsert_engagement(
            role_title=role_title,
            department=department,
            status=status,
            location=location,
            comp_band=comp_band,
            must_haves=must_haves,
            description=description,
        )
        engagement = talent_store.get_engagement(engagement_id)
    except Exception as exc:
        logger.exception("create_engagement: failed")
        return _err("create_engagement", str(exc))

    if engagement is None:
        return _err("create_engagement", f"created engagement {engagement_id} but could not reload it")

    _audit("create_engagement", "write", True,
           f"create_engagement {engagement_id} {role_title}",
           {"engagement_id": engagement_id, "role_title": role_title, "department": department})
    return json.dumps({"status": "ok", "engagement": engagement.model_dump()})


async def handle_create_candidate(tool_input: dict[str, Any]) -> str:
    from openexecutive.config import get_settings
    from openexecutive.knowledge.store import ChromaDBStore
    from openexecutive.talent import graph as talent_graph
    from openexecutive.talent import store as talent_store

    try:
        engagement_id = int(tool_input["engagement_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("create_candidate", f"bad arguments: {exc}")

    full_name = str(tool_input.get("full_name", "")).strip()
    if not full_name:
        return _err("create_candidate", "full_name is required")

    stage = CandidateStage.LEAD
    stage_raw = tool_input.get("stage")
    if stage_raw is not None:
        try:
            stage = CandidateStage(str(stage_raw))
        except ValueError:
            return _err("create_candidate", f"invalid stage: {stage_raw!r}")

    # Require an existing engagement — a candidate only exists within a search.
    if talent_store.get_engagement(engagement_id) is None:
        _audit("create_candidate", "write", False,
               f"create_candidate unknown engagement {engagement_id}",
               {"engagement_id": engagement_id})
        return json.dumps({"status": "not_found", "engagement_id": engagement_id})

    # email / linkedin_url are nullable columns (None == absent), so blanks
    # normalize to None; the other optionals are NOT NULL DEFAULT '' columns, so
    # they coerce to "". This matches the model, the schema, and the /talent form.
    def _norm(key: str) -> str | None:
        val = tool_input.get(key)
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    current_title = str(tool_input.get("current_title", "") or "")
    current_company = str(tool_input.get("current_company", "") or "")
    location = str(tool_input.get("location", "") or "")
    source = str(tool_input.get("source", "") or "")
    notes = str(tool_input.get("notes", "") or "")
    email = _norm("email")
    linkedin_url = _norm("linkedin_url")
    length_err = _length_error("create_candidate", [
        ("full_name", full_name, _MAX_SHORT),
        ("current_title", current_title, _MAX_SHORT),
        ("current_company", current_company, _MAX_SHORT),
        ("location", location, _MAX_SHORT),
        ("source", source, _MAX_SHORT),
        ("email", email or "", _MAX_SHORT),
        ("linkedin_url", linkedin_url or "", _MAX_SHORT),
        ("notes", notes, _MAX_LONG),
    ])
    if length_err:
        return length_err

    try:
        candidate_id = talent_store.upsert_candidate(
            engagement_id=engagement_id,
            full_name=full_name,
            current_title=current_title,
            current_company=current_company,
            location=location,
            email=email,
            linkedin_url=linkedin_url,
            source=source,
            stage=stage,
            notes=notes,
        )
        candidate = talent_store.get_candidate(candidate_id)
    except Exception as exc:
        logger.exception("create_candidate: failed")
        return _err("create_candidate", str(exc))

    if candidate is None:
        return _err("create_candidate", f"created candidate {candidate_id} but could not reload it")

    # Index into the talent graph so match_candidates / find_similar see the new
    # person. The store is pure SQLite, so indexing is the caller's job — the
    # /talent API route does the same after an insert. index_candidate swallows
    # its own vector-store failures, so a bad index never fails the create.
    try:
        store = ChromaDBStore(persist_directory=get_settings().vector_store_path)
        talent_graph.index_candidate(candidate, store)
    except Exception:  # noqa: BLE001 — index sync must never break the write
        logger.warning("create_candidate: indexing %s failed", candidate_id, exc_info=True)

    _audit("create_candidate", "write", True,
           f"create_candidate {candidate_id} {full_name} (engagement {engagement_id})",
           {"candidate_id": candidate_id, "engagement_id": engagement_id, "full_name": full_name})
    return json.dumps({"status": "ok", "candidate": candidate.model_dump()})


def _offer_summary(offer: Any) -> dict[str, Any]:
    return {
        "offer_id": offer.id,
        "candidate_id": offer.candidate_id,
        "engagement_id": offer.engagement_id,
        "status": offer.status.value,
        "comp_summary": offer.comp_summary,
        "note": offer.note,
        "expires_at": offer.expires_at,
        "extended_at": offer.extended_at,
        "decided_at": offer.decided_at,
    }


async def handle_list_offers(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    candidate_id: int | None = None
    engagement_id: int | None = None
    try:
        if tool_input.get("candidate_id") is not None:
            candidate_id = int(tool_input["candidate_id"])
        if tool_input.get("engagement_id") is not None:
            engagement_id = int(tool_input["engagement_id"])
    except (TypeError, ValueError) as exc:
        return _err("list_offers", f"bad arguments: {exc}")

    status: OfferStatus | None = None
    status_raw = tool_input.get("status")
    if status_raw is not None:
        try:
            status = OfferStatus(str(status_raw))
        except ValueError:
            return _err("list_offers", f"invalid status: {status_raw!r}")

    try:
        offers = talent_store.list_offers(
            candidate_id=candidate_id, engagement_id=engagement_id, status=status
        )
    except Exception as exc:
        logger.exception("list_offers: failed")
        return _err("list_offers", str(exc))

    out = [_offer_summary(o) for o in offers]
    _audit("list_offers", "read", True, f"list_offers returned {len(out)}",
           {"count": len(out), "candidate_id": candidate_id, "engagement_id": engagement_id})
    return json.dumps({"offers": out, "count": len(out)})


async def handle_create_offer(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent import store as talent_store

    try:
        candidate_id = int(tool_input["candidate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("create_offer", f"bad arguments: {exc}")

    comp_summary = str(tool_input.get("comp_summary", "")).strip()
    if not comp_summary:
        return _err("create_offer", "comp_summary is required")
    note = str(tool_input.get("note", "") or "")
    length_err = _length_error("create_offer", [
        ("comp_summary", comp_summary, _MAX_LONG),
        ("note", note, _MAX_LONG),
    ])
    if length_err:
        return length_err

    candidate = talent_store.get_candidate(candidate_id)
    if candidate is None:
        _audit("create_offer", "write", False,
               f"create_offer unknown candidate {candidate_id}",
               {"candidate_id": candidate_id})
        return json.dumps({"status": "not_found", "candidate_id": candidate_id})

    try:
        offer_id = talent_store.create_offer(
            candidate_id=candidate_id,
            engagement_id=candidate.engagement_id,
            comp_summary=comp_summary,
            note=note,
        )
        offer = talent_store.get_offer(offer_id)
    except ValueError as exc:
        return _err("create_offer", str(exc))
    except Exception as exc:
        logger.exception("create_offer: failed")
        return _err("create_offer", str(exc))

    if offer is None:
        return _err("create_offer", f"created offer {offer_id} but could not reload it")

    _audit("create_offer", "write", True,
           f"create_offer {offer_id} for candidate {candidate_id}",
           {"offer_id": offer_id, "candidate_id": candidate_id})
    return json.dumps({
        "status": "ok",
        "offer": _offer_summary(offer),
        "presentation_hint": (
            "Draft recorded. When the principal actually sends the offer, call "
            "extend_offer to start expiry reminders. OE never sends offers to "
            "candidates."
        ),
    })


async def handle_extend_offer(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent.offers import OfferActionError, extend_offer

    try:
        offer_id = int(tool_input["offer_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err("extend_offer", f"bad arguments: {exc}")

    expires_in_days = 7
    if tool_input.get("expires_in_days") is not None:
        try:
            expires_in_days = int(tool_input["expires_in_days"])
        except (TypeError, ValueError):
            return _err("extend_offer", "expires_in_days must be an integer")
        if not 1 <= expires_in_days <= 60:
            return _err("extend_offer", "expires_in_days must be 1-60")
    expires_at = tool_input.get("expires_at")
    note = tool_input.get("note")

    try:
        result = extend_offer(
            offer_id,
            expires_at=str(expires_at) if expires_at else None,
            expires_in_days=expires_in_days,
            note=str(note) if note is not None else None,
        )
    except OfferActionError as exc:
        return _err("extend_offer", exc.message)
    except Exception as exc:
        logger.exception("extend_offer: failed")
        return _err("extend_offer", str(exc))

    _audit("extend_offer", "write", True,
           f"extend_offer {offer_id} (approval: {result.approval_state}, "
           f"{len(result.nudge_action_ids)} nudges)",
           {"offer_id": offer_id, "approval_state": result.approval_state,
            "nudge_action_ids": result.nudge_action_ids})
    return json.dumps({
        "status": "ok",
        "offer": _offer_summary(result.offer),
        "approval_state": result.approval_state,
        "nudges_scheduled": len(result.nudge_action_ids),
        "warnings": result.warnings,
    })


async def handle_record_offer_decision(tool_input: dict[str, Any]) -> str:
    from openexecutive.talent.offers import OfferActionError, record_offer_decision

    try:
        offer_id = int(tool_input["offer_id"])
        decision = OfferStatus(str(tool_input["decision"]))
    except (KeyError, TypeError, ValueError) as exc:
        return _err("record_offer_decision", f"bad arguments: {exc}")

    note = tool_input.get("note")
    try:
        result = record_offer_decision(
            offer_id, decision, note=str(note) if note is not None else None
        )
    except OfferActionError as exc:
        return _err("record_offer_decision", exc.message)
    except Exception as exc:
        logger.exception("record_offer_decision: failed")
        return _err("record_offer_decision", str(exc))

    _audit("record_offer_decision", "write", True,
           f"record_offer_decision {offer_id} -> {decision.value}",
           {"offer_id": offer_id, "decision": decision.value,
            "side_effects": result.side_effects})
    out: dict[str, Any] = {
        "status": "ok",
        "offer": _offer_summary(result.offer),
        "side_effects": result.side_effects,
        "cancelled_nudges": result.cancelled_nudges,
    }
    if decision is OfferStatus.ACCEPTED:
        out["next_step"] = (
            "Run start_talent_workflow('new_hire_onboarding', "
            f"{{'candidate_id': {result.offer.candidate_id}}}) to add the hire "
            "to the roster, draft the 30/60/90 plan, and schedule check-ins."
        )
    return json.dumps(out)


TALENT_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "list_engagements": handle_list_engagements,
    "list_candidates": handle_list_candidates,
    "get_candidate": handle_get_candidate,
    "match_candidates": handle_match_candidates,
    "create_engagement": handle_create_engagement,
    "create_candidate": handle_create_candidate,
    "set_candidate_stage": handle_set_candidate_stage,
    "start_talent_workflow": handle_start_talent_workflow,
    "list_offers": handle_list_offers,
    "create_offer": handle_create_offer,
    "extend_offer": handle_extend_offer,
    "record_offer_decision": handle_record_offer_decision,
}


__all__ = [
    "TALENT_TOOLS",
    "TALENT_TOOL_HANDLERS",
]
