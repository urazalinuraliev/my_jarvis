"""HTTP-level tests for the staff-onboarding routes.

Exercises the FastAPI contract (status codes, 404/400 paths, template
instantiation through the route) that the store-level tests don't cover.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import staff_onboarding as route
from openexecutive.staff_onboarding import store


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_template_crud_via_http(client: TestClient) -> None:
    body = {
        "name": "eng_default",
        "title": "Engineering Onboarding",
        "department": "engineering",
        "ramp_days": 5,
        "task_specs": [
            {"title": "Provision laptop", "phase": "pre_start",
             "owner_role": "it", "due_offset_days": -2},
        ],
        "brief_sections": ["company_landscape"],
    }
    resp = client.put("/onboarding-templates/eng_default", json=body)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Engineering Onboarding"

    # Name mismatch between path and body is a 400.
    assert client.put("/onboarding-templates/other", json=body).status_code == 400

    assert client.get("/onboarding-templates/eng_default").status_code == 200
    assert client.get("/onboarding-templates/missing").status_code == 404
    assert {t["name"] for t in client.get("/onboarding-templates").json()} == {"eng_default"}

    # ramp_days cap (90) — the boundary value is accepted, one past it is a 422.
    # Guards against the route/model constraint drifting apart again.
    assert client.put(
        "/onboarding-templates/eng_default", json={**body, "ramp_days": 90}
    ).status_code == 200
    assert client.put(
        "/onboarding-templates/eng_default", json={**body, "ramp_days": 91}
    ).status_code == 422


def test_plan_instantiation_and_tasks_via_http(client: TestClient) -> None:
    client.put(
        "/onboarding-templates/generic",
        json={
            "name": "generic",
            "title": "Generic",
            "task_specs": [
                {"title": "1:1 with manager", "phase": "week_1",
                 "owner_role": "manager", "due_offset_days": 1},
            ],
            "brief_sections": [],
        },
    )

    # Create a plan from the template — task is instantiated with a due date.
    resp = client.post(
        "/onboarding-plans",
        json={
            "full_name": "Priya Rao",
            "start_date": "2026-07-01",
            "role": "CFO",
            "template_name": "generic",
            "manager_person_id": 200,
        },
    )
    assert resp.status_code == 201
    plan = resp.json()
    plan_id = plan["id"]
    assert plan["status"] == "draft"
    assert len(plan["tasks"]) == 1
    assert plan["tasks"][0]["due_date"] == "2026-07-02"
    assert plan["tasks"][0]["owner_person_id"] == 200
    task_id = plan["tasks"][0]["id"]

    # Unknown template → 404.
    assert client.post(
        "/onboarding-plans",
        json={"full_name": "X", "start_date": "2026-07-01", "template_name": "nope"},
    ).status_code == 404

    # Complete the task → plan completion rolls to 100%.
    resp = client.post(f"/onboarding-tasks/{task_id}/status",
                       json={"status": "done", "completed_by_person_id": 200})
    assert resp.status_code == 200
    assert resp.json()["completed_at"] is not None
    assert client.get(f"/onboarding-plans/{plan_id}").json()["completion_pct"] == 100

    # Advance phase pre_start → week_1.
    assert client.post(f"/onboarding-plans/{plan_id}/advance").json()["current_phase"] == "week_1"

    # Archive hides it from the default list.
    assert client.post(f"/onboarding-plans/{plan_id}/archive").status_code == 204
    assert client.get("/onboarding-plans").json() == []

    # 404s on missing ids.
    assert client.get("/onboarding-plans/99999").status_code == 404
    assert client.post("/onboarding-tasks/99999/status",
                       json={"status": "done"}).status_code == 404
