"""HTTP surface for the workflows package.

Endpoints:
- GET    /workflows                       List available workflows with metadata
- GET    /workflows/{name}                Get one workflow's metadata + input schema
- POST   /workflows/{name}/runs           Start a run; streams progress as SSE
- GET    /workflows/runs                  List recent runs across all workflows
- GET    /workflows/runs/{run_id}         Get a specific past run (with artifact)
- DELETE /workflows/runs/{run_id}         Delete a past run
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from openexecutive.workflows import (
    get_workflow,
    list_workflows,
)
from openexecutive.workflows.dynamic_models import (
    DynamicWorkflowDef,
    validate_definition,
)
from openexecutive.workflows.dynamic_store import (
    delete_definition,
    get_definition,
    list_definitions,
    set_active,
    upsert_definition,
)
from openexecutive.workflows.persistence import (
    complete_run,
    create_run,
    delete_run,
    fail_run,
    get_run,
    initialize_runs_db,
    list_runs,
    save_checkpoint,
)
from openexecutive.workflows.wait_for_human import WaitForHumanEvent

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/workflows")
async def list_workflow_meta() -> dict[str, Any]:
    """Public catalog of available workflows."""
    return {"workflows": [w.meta().model_dump() for w in list_workflows()]}


@router.get("/workflows/runs")
async def list_workflow_runs(workflow: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Recent runs across all workflows (or filtered by workflow name)."""
    initialize_runs_db()
    return {"runs": list_runs(workflow_name=workflow, limit=limit)}


@router.get("/workflows/runs/{run_id}")
async def get_workflow_run(run_id: str) -> dict[str, Any]:
    """Full record of one run, including the artifact if complete."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.delete("/workflows/runs/{run_id}")
async def delete_workflow_run(run_id: str) -> dict[str, str]:
    if not delete_run(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {"status": "deleted", "run_id": run_id}


# -----------------------------------------------------------------------------
# Dynamic (user-created) workflow CRUD. Declared BEFORE "/workflows/{name}" so
# the literal "custom" segment isn't captured by the {name} path parameter.
# -----------------------------------------------------------------------------


@router.get("/workflows/custom")
async def list_custom_workflows() -> dict[str, Any]:
    """All dynamic definitions (active and inactive) for the builder UI."""
    return {"definitions": [d.model_dump() for d in list_definitions(active_only=False)]}


@router.post("/workflows/custom", status_code=201)
async def create_custom_workflow(request: Request) -> dict[str, Any]:
    """Create a new dynamic workflow definition from a builder-UI submission."""
    defn = await _parse_definition(request)
    if get_definition(defn.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"A custom workflow named {defn.name!r} already exists"
        )
    errors = validate_definition(defn)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    stored = upsert_definition(defn)
    _sync_cadence(stored)
    return stored.model_dump()


@router.get("/workflows/custom/{name}")
async def get_custom_workflow(name: str) -> dict[str, Any]:
    defn = get_definition(name)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Custom workflow {name!r} not found")
    return defn.model_dump()


@router.put("/workflows/custom/{name}")
async def update_custom_workflow(name: str, request: Request) -> dict[str, Any]:
    if get_definition(name) is None:
        raise HTTPException(status_code=404, detail=f"Custom workflow {name!r} not found")
    defn = await _parse_definition(request)
    if defn.name != name:
        raise HTTPException(
            status_code=422, detail="definition name does not match the path name"
        )
    errors = validate_definition(defn)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    stored = upsert_definition(defn)
    _sync_cadence(stored)
    return stored.model_dump()


@router.delete("/workflows/custom/{name}")
async def delete_custom_workflow(name: str) -> dict[str, str]:
    from openexecutive.workflows.dynamic_cadence import cancel_cadence_rows

    cancel_cadence_rows(name)
    if not delete_definition(name):
        raise HTTPException(status_code=404, detail=f"Custom workflow {name!r} not found")
    return {"status": "deleted", "name": name}


@router.post("/workflows/custom/{name}/activate")
async def activate_custom_workflow(name: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    is_active = bool(body.get("is_active", True))
    if not set_active(name, is_active):
        raise HTTPException(status_code=404, detail=f"Custom workflow {name!r} not found")
    defn = get_definition(name)
    assert defn is not None
    _sync_cadence(defn)
    return defn.model_dump()


@router.get("/workflows/{name}")
async def get_workflow_meta(name: str) -> dict[str, Any]:
    try:
        workflow = get_workflow(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return workflow.meta().model_dump()


@router.get("/workflows/{name}/sample")
async def get_workflow_sample(name: str) -> dict[str, Any]:
    """Realistic sample inputs for the 'Load sample run' button.

    Returns 404 if the workflow does not exist or has no sample defined.
    """
    try:
        workflow = get_workflow(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    sample = workflow.sample_inputs()
    if sample is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow {name!r} does not expose a sample"
        )
    return {"workflow": name, "inputs": sample}


@router.post("/workflows/{name}/runs")
async def start_workflow_run(name: str, request: Request) -> StreamingResponse:
    """Start a workflow run. Streams progress events as Server-Sent Events.

    Each SSE event is a JSON-encoded `WorkflowEvent`. The final event in
    a successful run is `{"type": "done", "run_id": "..."}`.
    """
    try:
        workflow = get_workflow(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    input_model_cls = workflow.input_model()
    try:
        inputs = input_model_cls.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e

    run_id = uuid.uuid4().hex
    title = _derive_title(workflow.name, payload)
    create_run(
        run_id=run_id,
        workflow_name=workflow.name,
        title=title,
        inputs=payload,
    )

    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")

    async def event_stream():
        t_start = time.monotonic()
        artifact: str = ""
        paused = False
        try:
            # Tell the client which run_id to track and what the planned steps are.
            yield _sse({
                "type": "run_created",
                "run_id": run_id,
                "title": title,
                "workflow": workflow.name,
                "steps": [s.model_dump() for s in workflow.steps()],
            })

            async for event in workflow.run(inputs=inputs, store=store):
                # An approval-gate step yields a WaitForHumanEvent (not a
                # WorkflowEvent): checkpoint the run, tell the client it is
                # paused, and stop. The resumer applies the timeout policy;
                # the inbound resolver records the human's reply.
                if isinstance(event, WaitForHumanEvent):
                    until = datetime.now(UTC) + timedelta(hours=event.timeout_hours)
                    save_checkpoint(
                        run_id=run_id,
                        state_json=event.model_dump_json(),
                        awaiting_person_id=event.person_id,
                        awaiting_until=until,
                    )
                    paused = True
                    yield _sse({
                        "type": "awaiting_human",
                        "run_id": run_id,
                        "person_id": event.person_id,
                        "question": event.question,
                        "awaiting_until": until.isoformat(),
                    })
                    break

                event_dict = event.model_dump()
                if event.type == "artifact" and event.content is not None:
                    artifact = event.content
                yield _sse(event_dict)

            if paused:
                pass  # run left in 'awaiting_human'; no done/error emitted
            elif artifact:
                complete_run(run_id=run_id, artifact=artifact)
                yield _sse({"type": "done", "run_id": run_id})
            else:
                fail_run(run_id=run_id, error="Workflow finished without producing an artifact")
                yield _sse({
                    "type": "error",
                    "run_id": run_id,
                    "message": "Workflow finished without producing an artifact",
                })
        except Exception as exc:  # noqa: BLE001 — must report any failure to the client
            logger.exception("workflow.run_failed run_id=%s workflow=%s", run_id, workflow.name)
            fail_run(run_id=run_id, error=str(exc))
            yield _sse({"type": "error", "run_id": run_id, "message": str(exc)})
        finally:
            logger.info(
                "workflow.run_complete run_id=%s workflow=%s duration_s=%.2f",
                run_id,
                workflow.name,
                time.monotonic() - t_start,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _parse_definition(request: Request) -> DynamicWorkflowDef:
    """Parse + shape-validate a DynamicWorkflowDef from a request body."""
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
    try:
        return DynamicWorkflowDef.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e


def _sync_cadence(defn: DynamicWorkflowDef) -> None:
    """Reconcile the scheduler rows for a definition's cadence.

    Cancels any existing pending dynamic_workflow rows for this workflow, then
    enqueues the next occurrence if the (active) definition has a cadence. Used
    on create/update/activate so the schedule always matches the stored def.
    """
    from openexecutive.workflows.dynamic_cadence import (
        cancel_cadence_rows,
        schedule_dynamic_workflow_cadence,
    )

    cancel_cadence_rows(defn.name)
    if defn.is_active and defn.cadence:
        schedule_dynamic_workflow_cadence(defn)


_TITLE_MAX = 80


def _derive_title(workflow_name: str, payload: dict[str, Any]) -> str:
    """Best-effort short title for a run, surfaced in lists."""
    # Resolve via get_workflow (not WORKFLOW_REGISTRY) so dynamic, user-created
    # workflows get a real title instead of a KeyError.
    try:
        workflow = get_workflow(workflow_name)
    except KeyError:
        return workflow_name
    # Prefer a payload field that looks like a period/quarter label.
    for field in ("quarter_label", "period", "title", "topic"):
        if field in payload and payload[field]:
            base = f"{workflow.title} — {payload[field]}"
            return base[:_TITLE_MAX]
    return workflow.title
