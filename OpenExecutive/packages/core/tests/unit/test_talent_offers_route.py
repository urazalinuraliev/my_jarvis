"""HTTP-level tests for the /offers routes (close-the-hire-loop)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import talent as talent_route
from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.talent import store as talent_store
from openexecutive.workflows import persistence as wf_persistence


class _NoopStore:
    def add_documents(self, *a, **k) -> None: ...
    def delete_documents(self, *a, **k) -> None: ...
    def query(self, *a, **k):  # noqa: ANN001, ANN201
        return []


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "shared.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    monkeypatch.setattr(people_store, "DB_PATH", path)
    monkeypatch.setattr(episodic, "DB_PATH", path)
    monkeypatch.setattr(wf_persistence, "DB_PATH", path)
    episodic.initialize_db(path)
    people_store.initialize_db(path)
    talent_store.initialize_db(path)
    wf_persistence.initialize_runs_db(path)

    app = FastAPI()
    app.include_router(talent_route.router)
    app.state.store = _NoopStore()
    return TestClient(app)


def _seed_candidate(client: TestClient) -> int:
    eng = client.post("/engagements", json={"role_title": "VP Drilling"})
    assert eng.status_code == 201
    cand = client.post(
        "/candidates",
        json={
            "engagement_id": eng.json()["id"],
            "full_name": "Dana Cole",
            "stage": "interviewed",
        },
    )
    assert cand.status_code == 201
    return cand.json()["id"]


def _seed_principal() -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email="boss@example.com",
        preferred_channel="email",  # type: ignore[arg-type]
    )


def _create_offer(client: TestClient, candidate_id: int) -> int:
    resp = client.post(
        "/offers", json={"candidate_id": candidate_id, "comp_summary": "base 300k"}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_offers_empty(client: TestClient) -> None:
    assert client.get("/offers").json() == []


def test_create_get_list_offer(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    oid = _create_offer(client, cand_id)

    got = client.get(f"/offers/{oid}")
    assert got.status_code == 200
    assert got.json()["status"] == "draft"
    assert got.json()["comp_summary"] == "base 300k"

    assert len(client.get("/offers").json()) == 1
    assert client.get(f"/offers?candidate_id={cand_id}").json()[0]["id"] == oid
    assert client.get("/offers?status=extended").json() == []


def test_create_offer_404_unknown_candidate(client: TestClient) -> None:
    resp = client.post("/offers", json={"candidate_id": 999, "comp_summary": "x"})
    assert resp.status_code == 404


def test_create_offer_409_when_open_offer_exists(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    _create_offer(client, cand_id)
    resp = client.post("/offers", json={"candidate_id": cand_id, "comp_summary": "y"})
    assert resp.status_code == 409


def test_patch_offer_terms_only_while_pre_extension(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    _seed_principal()
    oid = _create_offer(client, cand_id)

    resp = client.patch(f"/offers/{oid}", json={"comp_summary": "base 320k"})
    assert resp.status_code == 200
    assert resp.json()["comp_summary"] == "base 320k"

    assert client.post(f"/offers/{oid}/extend", json={}).status_code == 200
    resp = client.patch(f"/offers/{oid}", json={"comp_summary": "base 999k"})
    assert resp.status_code == 409


def test_extend_then_decide_accepted(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    _seed_principal()
    oid = _create_offer(client, cand_id)

    ext = client.post(f"/offers/{oid}/extend", json={"expires_in_days": 7})
    assert ext.status_code == 200
    body = ext.json()
    assert body["offer"]["status"] == "extended"
    assert body["nudges_scheduled"] == 3
    assert body["approval_state"] == "none"
    assert body["warnings"]  # extended without recorded sign-off → flagged

    dec = client.post(f"/offers/{oid}/decision", json={"decision": "accepted"})
    assert dec.status_code == 200
    body = dec.json()
    assert body["offer"]["status"] == "accepted"
    assert body["cancelled_nudges"] == 3
    assert any("placed" in s for s in body["side_effects"])
    assert any("filled" in s for s in body["side_effects"])

    cand = client.get(f"/candidates/{cand_id}").json()
    assert cand["stage"] == "placed"
    eng = client.get(f"/engagements/{cand['engagement_id']}").json()
    assert eng["status"] == "filled"


def test_extend_bad_expiry_is_400(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    _seed_principal()
    oid = _create_offer(client, cand_id)
    resp = client.post(f"/offers/{oid}/extend", json={"expires_at": "not-a-date"})
    assert resp.status_code == 400


def test_extend_wrong_status_is_409(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    _seed_principal()
    oid = _create_offer(client, cand_id)
    client.post(f"/offers/{oid}/extend", json={})
    resp = client.post(f"/offers/{oid}/extend", json={})
    assert resp.status_code == 409


def test_decision_illegal_transition_is_409(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    oid = _create_offer(client, cand_id)  # still draft
    resp = client.post(f"/offers/{oid}/decision", json={"decision": "accepted"})
    assert resp.status_code == 409


def test_decision_unknown_offer_is_404(client: TestClient) -> None:
    resp = client.post("/offers/999/decision", json={"decision": "accepted"})
    assert resp.status_code == 404


def test_archive_offer(client: TestClient) -> None:
    cand_id = _seed_candidate(client)
    oid = _create_offer(client, cand_id)
    assert client.post(f"/offers/{oid}/archive").status_code == 204
    assert client.get("/offers").json() == []
    assert client.get("/offers?include_archived=true").json()[0]["id"] == oid
    assert client.post("/offers/999/archive").status_code == 404
