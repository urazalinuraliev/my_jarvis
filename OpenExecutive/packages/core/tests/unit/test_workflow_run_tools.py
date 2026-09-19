"""Unit tests for openexecutive.orchestrator.workflow_run_tools.

These chat tools let the Executive list and launch any workflow from a chat
turn. ``list_workflows`` and the validation/refusal branches of ``run_workflow``
run against the real registry; the happy path and the approval-gate path use a
stub workflow + a tmp run DB so no Anthropic API or vector store is needed.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from openexecutive.orchestrator.workflow_run_tools import (
    handle_list_workflows,
    handle_run_workflow,
)
from openexecutive.workflows.base import WorkflowEvent
from openexecutive.workflows.wait_for_human import WaitForHumanEvent


def _call(fn: Callable[[dict[str, Any]], Awaitable[str]], payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(asyncio.run(fn(payload)))


# --------------------------------------------------------------------------- #
# Stub workflow used for the happy / gate paths
# --------------------------------------------------------------------------- #


class _StubInputs(BaseModel):
    topic: str


class _StubWorkflow:
    name = "stub"
    title = "Stub Workflow"

    def input_model(self) -> type[BaseModel]:
        return _StubInputs

    async def run(self, inputs: BaseModel, store: Any) -> AsyncIterator[WorkflowEvent]:
        yield WorkflowEvent(type="step_start", step_id="s1", step_title="Work")
        yield WorkflowEvent(type="artifact", content="# Stub artifact\n\nDone.")


class _GateWorkflow:
    name = "gate"
    title = "Gate Workflow"

    def input_model(self) -> type[BaseModel]:
        return _StubInputs

    async def run(self, inputs: BaseModel, store: Any) -> AsyncIterator[WorkflowEvent]:
        # Pause at an approval gate before producing any artifact.
        yield WaitForHumanEvent(person_id=3, question="Approve the plan?", timeout_hours=24)


class _ErrorThenArtifactWorkflow:
    name = "mixed"
    title = "Mixed Workflow"

    def input_model(self) -> type[BaseModel]:
        return _StubInputs

    async def run(self, inputs: BaseModel, store: Any) -> AsyncIterator[WorkflowEvent]:
        # A non-fatal error event followed by a real artifact: the artifact must win.
        yield WorkflowEvent(type="error", message="non-fatal note")
        yield WorkflowEvent(type="artifact", content="# Recovered artifact")


class _ErrorOnlyWorkflow:
    name = "boom"
    title = "Boom Workflow"

    def input_model(self) -> type[BaseModel]:
        return _StubInputs

    async def run(self, inputs: BaseModel, store: Any) -> AsyncIterator[WorkflowEvent]:
        yield WorkflowEvent(type="error", message="boom")


@pytest.fixture
def run_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point workflow-run persistence + the vector store at throwaway stand-ins."""
    from openexecutive.knowledge import store as knowledge_store
    from openexecutive.workflows import persistence

    db = tmp_path / "runs.db"
    monkeypatch.setattr(persistence, "DB_PATH", db)
    # The store is never touched by the stub workflows; a no-op stand-in keeps
    # the handler from constructing a real (heavy) ChromaDB instance.
    monkeypatch.setattr(knowledge_store, "ChromaDBStore", lambda *a, **k: object())
    return db


# --------------------------------------------------------------------------- #
# list_workflows
# --------------------------------------------------------------------------- #


def test_list_workflows_returns_builtins_with_inputs() -> None:
    out = _call(handle_list_workflows, {})
    assert out["count"] >= 1
    names = {w["name"] for w in out["workflows"]}
    # A representative built-in is present, with the compact metadata shape.
    assert "board_prep" in names
    sample = next(w for w in out["workflows"] if w["name"] == "board_prep")
    assert {"name", "title", "description", "section", "estimated_minutes", "inputs"} <= sample.keys()
    assert isinstance(sample["inputs"], dict)


def test_list_workflows_excludes_blocklist() -> None:
    out = _call(handle_list_workflows, {})
    names = {w["name"] for w in out["workflows"]}
    assert "executive_research" not in names


# --------------------------------------------------------------------------- #
# run_workflow — refusal / validation branches (real registry, no API)
# --------------------------------------------------------------------------- #


def test_run_workflow_missing_name() -> None:
    out = _call(handle_run_workflow, {"inputs": {}})
    assert "error" in out


def test_run_workflow_unknown_name() -> None:
    out = _call(handle_run_workflow, {"workflow": "not_a_workflow", "inputs": {}})
    assert "error" in out
    assert "unknown workflow" in out["error"]


def test_run_workflow_blocklisted_name_refused() -> None:
    out = _call(handle_run_workflow, {"workflow": "executive_research", "inputs": {}})
    assert "error" in out
    assert "run_executive_research" in out["error"]


def test_run_workflow_inputs_must_be_object(monkeypatch: pytest.MonkeyPatch) -> None:
    from openexecutive import workflows as wf_pkg

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _StubWorkflow())
    out = _call(handle_run_workflow, {"workflow": "stub", "inputs": "nope"})
    assert "error" in out
    assert "inputs must be an object" in out["error"]


def test_run_workflow_invalid_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    from openexecutive import workflows as wf_pkg

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _StubWorkflow())
    # _StubInputs requires `topic`; an empty object must fail validation.
    out = _call(handle_run_workflow, {"workflow": "stub", "inputs": {}})
    assert "error" in out
    assert "invalid inputs" in out["error"]


# --------------------------------------------------------------------------- #
# run_workflow — happy path + approval gate (stub workflow + tmp run DB)
# --------------------------------------------------------------------------- #


def test_run_workflow_happy_path(monkeypatch: pytest.MonkeyPatch, run_db: Path) -> None:
    from openexecutive import workflows as wf_pkg
    from openexecutive.workflows import persistence

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _StubWorkflow())

    out = _call(handle_run_workflow, {"workflow": "stub", "inputs": {"topic": "x"}})
    assert out["ok"] is True
    assert out["artifact"].startswith("# Stub artifact")
    run = persistence.get_run(out["run_id"], db_path=run_db)
    assert run is not None
    assert run["status"] == "done"


def test_run_workflow_awaiting_human(monkeypatch: pytest.MonkeyPatch, run_db: Path) -> None:
    from openexecutive import workflows as wf_pkg
    from openexecutive.workflows import persistence

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _GateWorkflow())

    out = _call(handle_run_workflow, {"workflow": "gate", "inputs": {"topic": "x"}})
    assert out["status"] == "awaiting_human"
    assert out["person_id"] == 3
    # The run is checkpointed (not completed or failed).
    run = persistence.get_run(out["run_id"], db_path=run_db)
    assert run is not None
    assert run["status"] == "awaiting_human"


def test_run_workflow_artifact_wins_over_error_event(
    monkeypatch: pytest.MonkeyPatch, run_db: Path
) -> None:
    """A non-fatal `error` event must not discard a produced artifact."""
    from openexecutive import workflows as wf_pkg
    from openexecutive.workflows import persistence

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _ErrorThenArtifactWorkflow())

    out = _call(handle_run_workflow, {"workflow": "mixed", "inputs": {"topic": "x"}})
    assert out["ok"] is True
    assert out["artifact"].startswith("# Recovered artifact")
    run = persistence.get_run(out["run_id"], db_path=run_db)
    assert run is not None
    assert run["status"] == "done"


def test_run_workflow_error_only_fails_with_message(
    monkeypatch: pytest.MonkeyPatch, run_db: Path
) -> None:
    from openexecutive import workflows as wf_pkg
    from openexecutive.workflows import persistence

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _ErrorOnlyWorkflow())

    out = _call(handle_run_workflow, {"workflow": "boom", "inputs": {"topic": "x"}})
    assert "error" in out
    assert "boom" in out["error"]
    run = persistence.get_run(out["run_id"], db_path=run_db)
    assert run is not None
    assert run["status"] == "error"


def test_run_workflow_create_run_failure_fails_fast(
    monkeypatch: pytest.MonkeyPatch, run_db: Path
) -> None:
    """If the run row can't be created, refuse rather than run an untracked
    (and potentially orphaned) workflow."""
    from openexecutive import workflows as wf_pkg
    from openexecutive.workflows import persistence

    monkeypatch.setattr(wf_pkg, "get_workflow", lambda name: _GateWorkflow())

    def _boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(persistence, "create_run", _boom)

    out = _call(handle_run_workflow, {"workflow": "gate", "inputs": {"topic": "x"}})
    assert "error" in out
    assert "could not start run" in out["error"]
    # No awaiting_human claim was made.
    assert out.get("status") != "awaiting_human"
