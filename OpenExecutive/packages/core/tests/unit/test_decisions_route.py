"""Tests for the decisions API route (approve, reject, cancel, reliability)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from openexecutive.memory.decision_ledger import (
    create_decision_instance,
    mark_resolved,
)
from openexecutive.memory.episodic import initialize_db


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from openexecutive.alerts import store as alert_store
    from openexecutive.memory import episodic
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    # approve/reject/cancel clear the companion briefing alert — wire the
    # alerts store to the same isolated DB so the clear is observable in-test.
    monkeypatch.setattr(alert_store, "DB_PATH", db_path)
    initialize_db(db_path)
    alert_store.initialize_db(db_path)
    return db_path


def _seed_companion_alert(db: Path, instance_id: int) -> None:
    """Insert the briefing alert that calendar_tools links to a proposal."""
    from openexecutive.alerts.store import insert_alert
    insert_alert(
        source="decision_scheduling",
        external_id=f"decision:{instance_id}",
        severity="medium",
        headline="Approve meeting: Sync",
        body="...",
        topic_tags=[f"decision_instance:{instance_id}", "decision_class:meeting_scheduling"],
        dedup_key=f"decision:{instance_id}",
        routed_to_person_id=None,
        db_path=db,
    )


@pytest.fixture()
def client(db: Path) -> TestClient:
    from fastapi import FastAPI

    from openexecutive.api.routes.decisions import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _seed(db: Path, idem: str = "k1") -> int:
    return create_decision_instance(
        decision_class="meeting_scheduling",
        department="operations",
        originating_session_id=None,
        proposed_payload={
            "title": "Sync",
            "start": "2025-06-15T10:00:00+00:00",
            "end": "2025-06-15T11:00:00+00:00",
            "attendee_emails": ["alice@example.com"],
            "description": "",
        },
        idempotency_key=idem,
        gate_mode="propose",
        approver_person_id=None,
        confidence=0.8,
        db_path=db,
    )


# ---------------------------------------------------------------------------
# GET /decisions
# ---------------------------------------------------------------------------

def test_list_empty(client: TestClient) -> None:
    res = client.get("/decisions")
    assert res.status_code == 200
    assert res.json() == []


def test_list_returns_instance(client: TestClient, db: Path) -> None:
    _seed(db)
    res = client.get("/decisions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["status"] == "proposed"


def test_list_status_filter(client: TestClient, db: Path) -> None:
    iid = _seed(db, "k1")
    _seed(db, "k2")
    mark_resolved(iid, "rejected", db_path=db)
    res = client.get("/decisions?status=proposed")
    assert len(res.json()) == 1


# ---------------------------------------------------------------------------
# GET /decisions/{id}
# ---------------------------------------------------------------------------

def test_get_instance(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    res = client.get(f"/decisions/{iid}")
    assert res.status_code == 200
    assert res.json()["id"] == iid


def test_get_missing_404(client: TestClient) -> None:
    res = client.get("/decisions/99999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /decisions/{id}/approve
# ---------------------------------------------------------------------------

def test_approve_creates_event(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    fake_gw = type("GW", (), {})()
    fake_gw.call_tool = AsyncMock(return_value=json.dumps({"id": "evt-approve-test"}))

    # Also mock freebusy (returns no conflicts)
    async def _call_tool(args: dict) -> str:
        if args.get("name") == "google_workspace__query_freebusy":
            return json.dumps({"has_conflicts": False})
        return json.dumps({"id": "evt-approve-test"})
    fake_gw.call_tool = AsyncMock(side_effect=_call_tool)

    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=fake_gw):
        res = client.post(f"/decisions/{iid}/approve", json={})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "approved_unchanged"
    assert data["external_event_id"] == "evt-approve-test"


def test_approve_with_edit_sets_approved_with_edit(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    fake_gw = type("GW", (), {})()

    async def _call_tool(args: dict) -> str:
        if args.get("name") == "google_workspace__query_freebusy":
            return json.dumps({})
        return json.dumps({"id": "evt-edit"})
    fake_gw.call_tool = AsyncMock(side_effect=_call_tool)

    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=fake_gw):
        res = client.post(
            f"/decisions/{iid}/approve",
            json={"edits": {"title": "Renamed Sync"}},
        )

    assert res.status_code == 200
    assert res.json()["status"] == "approved_with_edit"


def test_approve_already_approved_409(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    mark_resolved(iid, "approved_unchanged", db_path=db)

    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway",
               return_value=MagicMock()) as _:
        res = client.post(f"/decisions/{iid}/approve", json={})

    assert res.status_code == 409


def test_approve_missing_404(client: TestClient) -> None:
    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway",
               return_value=MagicMock()):
        res = client.post("/decisions/99999/approve", json={})
    assert res.status_code == 404


def test_double_approve_books_once(client: TestClient, db: Path) -> None:
    """Second approve on an already-approved row must 409, not double-book."""
    iid = _seed(db)
    fake_gw = type("GW", (), {})()

    async def _call_tool(args: dict) -> str:
        if "freebusy" in args.get("name", ""):
            return json.dumps({})
        return json.dumps({"id": "evt-x"})
    fake_gw.call_tool = AsyncMock(side_effect=_call_tool)

    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=fake_gw):
        r1 = client.post(f"/decisions/{iid}/approve", json={})
        r2 = client.post(f"/decisions/{iid}/approve", json={})

    assert r1.status_code == 200
    assert r2.status_code == 409
    assert fake_gw.call_tool.await_count == 2  # freebusy + create on first call


# ---------------------------------------------------------------------------
# POST /decisions/{id}/reject
# ---------------------------------------------------------------------------

def test_reject_sets_rejected(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    res = client.post(f"/decisions/{iid}/reject", json={"reason": "not needed"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


def test_reject_already_resolved_409(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    mark_resolved(iid, "rejected", db_path=db)
    res = client.post(f"/decisions/{iid}/reject", json={})
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# POST /decisions/{id}/cancel
# ---------------------------------------------------------------------------

def test_cancel_approved_event(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    mark_resolved(iid, "approved_unchanged", db_path=db)

    # Inject external_event_id directly so cancel knows the event exists.
    import sqlite3

    import openexecutive.memory.episodic as _ep
    with sqlite3.connect(str(_ep.DB_PATH)) as conn:
        conn.execute(
            "UPDATE decision_instances SET external_event_id = ? WHERE id = ?",
            ("evt-cancel-test", iid),
        )

    async def _call_tool(args: dict) -> str:
        return json.dumps({"status": "cancelled"})
    fake_gw = type("GW", (), {})()
    fake_gw.call_tool = AsyncMock(side_effect=_call_tool)

    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=fake_gw):
        res = client.post(f"/decisions/{iid}/cancel")

    assert res.status_code == 200
    assert res.json()["status"] == "reversed"
    fake_gw.call_tool.assert_awaited_once()


def test_cancel_unknown_404(client: TestClient) -> None:
    res = client.post("/decisions/99999/cancel")
    assert res.status_code == 404


def test_cancel_rejected_409(client: TestClient, db: Path) -> None:
    iid = _seed(db)
    mark_resolved(iid, "rejected", db_path=db)
    res = client.post(f"/decisions/{iid}/cancel")
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# GET /audit/reliability
# ---------------------------------------------------------------------------

def test_reliability_empty(client: TestClient) -> None:
    res = client.get("/audit/reliability?decision_class=meeting_scheduling&days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["volume"] == 0
    assert data["unchanged_approval_rate"] == 0.0


# ---------------------------------------------------------------------------
# Resolving a decision clears its companion briefing alert
# ---------------------------------------------------------------------------

def _approve_gateway() -> object:
    """Gateway whose freebusy reports no conflict and create returns an id."""
    async def _call_tool(args: dict) -> str:
        if args.get("name") == "google_workspace__query_freebusy":
            return json.dumps({"has_conflicts": False})
        return json.dumps({"id": "evt-clear-test"})
    gw = type("GW", (), {})()
    gw.call_tool = AsyncMock(side_effect=_call_tool)
    return gw


def test_approve_clears_linked_alert(client: TestClient, db: Path) -> None:
    from openexecutive.alerts.store import get_alert_by_external

    iid = _seed(db)
    _seed_companion_alert(db, iid)
    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=_approve_gateway()):
        res = client.post(f"/decisions/{iid}/approve", json={})
    assert res.status_code == 200
    alert = get_alert_by_external("decision_scheduling", f"decision:{iid}", db_path=db)
    assert alert is not None
    assert alert.status == "ack"


def test_reject_clears_linked_alert(client: TestClient, db: Path) -> None:
    from openexecutive.alerts.store import get_alert_by_external

    iid = _seed(db)
    _seed_companion_alert(db, iid)
    res = client.post(f"/decisions/{iid}/reject", json={"reason": "no"})
    assert res.status_code == 200
    alert = get_alert_by_external("decision_scheduling", f"decision:{iid}", db_path=db)
    assert alert is not None
    assert alert.status == "dismissed"


def test_cancel_clears_linked_alert(client: TestClient, db: Path) -> None:
    from openexecutive.alerts.store import get_alert_by_external

    iid = _seed(db)
    _seed_companion_alert(db, iid)
    # Cancel a still-proposed instance (no external event) → just reverses it.
    res = client.post(f"/decisions/{iid}/cancel")
    assert res.status_code == 200
    alert = get_alert_by_external("decision_scheduling", f"decision:{iid}", db_path=db)
    assert alert is not None
    assert alert.status == "dismissed"


def test_approve_with_no_linked_alert_still_succeeds(client: TestClient, db: Path) -> None:
    """The clear is best-effort: a decision with no companion alert (e.g.
    created before the bridge) still approves cleanly."""
    iid = _seed(db)  # no companion alert seeded
    with patch("openexecutive.orchestrator.mcp_gateway.get_active_gateway", return_value=_approve_gateway()):
        res = client.post(f"/decisions/{iid}/approve", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "approved_unchanged"


