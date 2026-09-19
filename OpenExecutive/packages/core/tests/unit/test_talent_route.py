"""HTTP-level tests for /engagements, /candidates routes (in-house hiring)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import talent as talent_route
from openexecutive.talent import store as talent_store


class _NoopStore:
    """No-op KnowledgeStore stand-in so candidate mutations can index without
    constructing a real ChromaDB (these tests don't assert on the index)."""

    def add_documents(self, *a, **k) -> None: ...
    def delete_documents(self, *a, **k) -> None: ...
    def query(self, *a, **k):  # noqa: ANN001, ANN201
        return []


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()

    app = FastAPI()
    app.include_router(talent_route.router)
    app.state.store = _NoopStore()
    return TestClient(app)


def _make_engagement(
    client: TestClient,
    *,
    role_title: str = "VP Drilling",
    department: str = "Drilling",
) -> int:
    resp = client.post(
        "/engagements",
        json={
            "role_title": role_title,
            "department": department,
            "must_haves": "10+ yrs upstream, cycle-tested",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# --------------------------------------------------------------------------- #
# Engagements
# --------------------------------------------------------------------------- #

def test_engagements_empty(client: TestClient) -> None:
    assert client.get("/engagements").json() == []


def test_engagement_create_stores_department(client: TestClient) -> None:
    # In-house hiring: only role_title is required; department is a free-text
    # in-house grouping (no external client to resolve).
    resp = client.post(
        "/engagements", json={"role_title": "CFO", "department": "Finance"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role_title"] == "CFO"
    assert body["department"] == "Finance"
    assert body["status"] == "open"
    assert "client_id" not in body


def test_engagement_crud_and_listing(client: TestClient) -> None:
    eid = _make_engagement(client)
    client.post("/engagements", json={"role_title": "CFO", "department": "Finance"})

    assert len(client.get("/engagements").json()) == 2

    patched = client.patch(f"/engagements/{eid}", json={"status": "filled"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "filled"
    assert patched.json()["role_title"] == "VP Drilling"  # unchanged
    assert patched.json()["department"] == "Drilling"  # unchanged


def test_engagement_get_unknown_404(client: TestClient) -> None:
    assert client.get("/engagements/9999").status_code == 404


def test_engagement_archive(client: TestClient) -> None:
    eid = _make_engagement(client)
    assert client.post(f"/engagements/{eid}/archive").status_code == 204
    assert client.get("/engagements").json() == []


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

def test_candidate_requires_existing_engagement(client: TestClient) -> None:
    resp = client.post(
        "/candidates", json={"engagement_id": 9999, "full_name": "Ghost"}
    )
    assert resp.status_code == 404


def test_candidate_crud_stage_and_filters(client: TestClient) -> None:
    eid = _make_engagement(client)
    create = client.post(
        "/candidates",
        json={
            "engagement_id": eid,
            "full_name": "Dana Cole",
            "current_title": "Drilling Director",
        },
    )
    assert create.status_code == 201
    cand_id = create.json()["id"]
    assert create.json()["stage"] == "lead"
    assert create.json()["fit_score"] is None

    # Advance stage via the dedicated endpoint.
    staged = client.post(f"/candidates/{cand_id}/stage", json={"stage": "interviewed"})
    assert staged.status_code == 200
    assert staged.json()["stage"] == "interviewed"

    # Filter by engagement + stage.
    by_stage = client.get(f"/candidates?engagement_id={eid}&stage=interviewed").json()
    assert len(by_stage) == 1
    assert by_stage[0]["id"] == cand_id

    # Patch leaves stage untouched.
    patched = client.patch(f"/candidates/{cand_id}", json={"location": "Midland, TX"})
    assert patched.json()["location"] == "Midland, TX"
    assert patched.json()["stage"] == "interviewed"

    assert client.post(f"/candidates/{cand_id}/archive").status_code == 204
    assert client.get(f"/candidates?engagement_id={eid}").json() == []


def test_candidate_patch_can_clear_nullable_email(client: TestClient) -> None:
    eid = _make_engagement(client)
    create = client.post(
        "/candidates",
        json={"engagement_id": eid, "full_name": "Dana", "email": "dana@example.com"},
    )
    cand_id = create.json()["id"]
    assert create.json()["email"] == "dana@example.com"

    # Explicit null clears the field; an omitted field would keep it.
    cleared = client.patch(f"/candidates/{cand_id}", json={"email": None})
    assert cleared.status_code == 200
    assert cleared.json()["email"] is None

    # Omitting email on a later patch must preserve the (now-null) value and
    # not resurrect the old one.
    other = client.patch(f"/candidates/{cand_id}", json={"location": "Midland"})
    assert other.json()["email"] is None


def test_candidate_patch_ignores_stage_field(client: TestClient) -> None:
    eid = _make_engagement(client)
    create = client.post("/candidates", json={"engagement_id": eid, "full_name": "Dana"})
    cand_id = create.json()["id"]
    # `stage` is not part of CandidatePatch; sending it must not change stage
    # (the dedicated /stage endpoint is the only way to move the pipeline).
    resp = client.patch(f"/candidates/{cand_id}", json={"stage": "placed", "notes": "x"})
    assert resp.status_code == 200
    assert resp.json()["stage"] == "lead"
    assert resp.json()["notes"] == "x"


def test_candidate_bad_stage_value_422(client: TestClient) -> None:
    eid = _make_engagement(client)
    create = client.post("/candidates", json={"engagement_id": eid, "full_name": "Dana"})
    cand_id = create.json()["id"]
    resp = client.post(f"/candidates/{cand_id}/stage", json={"stage": "not_a_stage"})
    assert resp.status_code == 422
