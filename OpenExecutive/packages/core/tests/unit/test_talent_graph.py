"""Tests for the talent graph (semantic candidate matching).

Uses an in-memory ranking fake store so there's no chromadb / embedding /
network dependency. The fake ranks by token overlap with the query, which is
enough to assert ordering, filtering, and the score mapping deterministically.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import talent as talent_route
from openexecutive.talent import graph as talent_graph
from openexecutive.talent import store as talent_store
from openexecutive.talent.graph import CANDIDATES_COLLECTION


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class RankingFakeStore:
    """In-memory KnowledgeStore that ranks by query/doc token overlap."""

    def __init__(self) -> None:
        self.collections: dict[str, list[dict[str, Any]]] = {}
        self.add_calls = 0

    def add_documents(self, texts, metadatas, ids, collection) -> None:
        self.add_calls += 1
        col = self.collections.setdefault(collection, [])
        for t, m, i in zip(texts, metadatas, ids, strict=False):
            col[:] = [r for r in col if r["id"] != i]
            col.append({"id": i, "text": t, "metadata": m})

    def delete_documents(self, collection, where) -> None:
        col = self.collections.get(collection, [])
        self.collections[collection] = [
            r for r in col
            if not all(r["metadata"].get(k) == v for k, v in where.items())
        ]

    def query(self, query_text, collection, domain_filter=None, n_results=5):
        col = self.collections.get(collection, [])
        q = _tokens(query_text)
        scored = []
        for r in col:
            overlap = len(q & _tokens(r["text"]))
            distance = 1.0 - (overlap / len(q) if q else 0.0)
            scored.append((distance, r))
        scored.sort(key=lambda x: x[0])
        return [
            {"text": r["text"], "metadata": r["metadata"], "distance": d}
            for d, r in scored[:n_results]
        ]


class ExplodingStore:
    """Raises on every op — to prove indexing is best-effort."""

    def add_documents(self, *a, **k):
        raise RuntimeError("vector store down")

    def delete_documents(self, *a, **k):
        raise RuntimeError("vector store down")

    def query(self, *a, **k):
        raise RuntimeError("vector store down")


def test_score_clamps_both_ends() -> None:
    from openexecutive.talent.graph import _score

    assert _score(0.0) == 1.0
    assert _score(0.2) == 0.8
    assert _score(1.5) == 0.0          # poor match clamps to 0
    assert _score(-0.0001) == 1.0      # float artifact clamps to 1, not >1
    assert _score(None) == 0.0


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _engagement(must_haves: str = "upstream drilling") -> int:
    return talent_store.upsert_engagement(
        role_title="VP Drilling", department="Drilling", must_haves=must_haves
    )


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #

def test_index_candidate_writes_doc_with_metadata(db: Path) -> None:
    eid = _engagement()
    cid = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", current_title="Drilling Director"
    )
    store = RankingFakeStore()
    talent_graph.index_candidate(talent_store.get_candidate(cid), store)  # type: ignore[arg-type]
    rows = store.collections[CANDIDATES_COLLECTION]
    assert len(rows) == 1
    assert rows[0]["metadata"]["candidate_id"] == cid
    assert rows[0]["metadata"]["engagement_id"] == eid
    assert rows[0]["metadata"]["stage"] == "lead"
    assert "Dana Cole" in rows[0]["text"]


def test_index_candidate_archived_is_removed(db: Path) -> None:
    eid = _engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    store = RankingFakeStore()
    talent_graph.index_candidate(talent_store.get_candidate(cid), store)  # type: ignore[arg-type]
    assert store.collections[CANDIDATES_COLLECTION]

    talent_store.archive_candidate(cid)
    talent_graph.index_candidate(talent_store.get_candidate(cid), store)  # type: ignore[arg-type]
    assert store.collections[CANDIDATES_COLLECTION] == []


def test_index_candidate_best_effort_swallows_errors(db: Path) -> None:
    eid = _engagement()
    cid = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    # Must not raise even though the store explodes.
    talent_graph.index_candidate(talent_store.get_candidate(cid), ExplodingStore())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

def test_match_ranks_pool_by_must_haves(db: Path) -> None:
    eid = _engagement(must_haves="offshore deepwater drilling subsea")
    store = RankingFakeStore()
    # Strong match on the must-haves vs. an unrelated finance profile.
    strong = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Strong Fit",
        current_title="Offshore Deepwater Drilling Lead", notes="subsea wells",
    )
    weak = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Weak Fit",
        current_title="Corporate Treasury Analyst", notes="hedging cash",
    )
    for c in (strong, weak):
        talent_graph.index_candidate(talent_store.get_candidate(c), store)  # type: ignore[arg-type]

    eng = talent_store.get_engagement(eid)
    matches = talent_graph.match_candidates_for_engagement(eng, store, limit=10)  # type: ignore[arg-type]
    assert [m["candidate_id"] for m in matches][0] == strong
    assert matches[0]["score"] >= matches[-1]["score"]
    assert all(0.0 <= m["score"] <= 1.0 for m in matches)


def test_match_respects_limit(db: Path) -> None:
    eid = _engagement()
    store = RankingFakeStore()
    for i in range(5):
        c = talent_store.upsert_candidate(
            engagement_id=eid, full_name=f"Cand {i}", current_title="Driller"
        )
        talent_graph.index_candidate(talent_store.get_candidate(c), store)  # type: ignore[arg-type]
    eng = talent_store.get_engagement(eid)
    assert len(talent_graph.match_candidates_for_engagement(eng, store, limit=2)) == 2  # type: ignore[arg-type]
    assert talent_graph.match_candidates_for_engagement(eng, store, limit=0) == []  # type: ignore[arg-type]


def test_match_empty_must_haves_returns_empty(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="")
    store = RankingFakeStore()
    eng = talent_store.get_engagement(eid)
    assert talent_graph.match_candidates_for_engagement(eng, store) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Similar
# --------------------------------------------------------------------------- #

def test_similar_excludes_self(db: Path) -> None:
    eid = _engagement()
    store = RankingFakeStore()
    a = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Alpha Driller", current_title="Drilling Engineer"
    )
    b = talent_store.upsert_candidate(
        engagement_id=eid, full_name="Beta Driller", current_title="Drilling Engineer"
    )
    for c in (a, b):
        talent_graph.index_candidate(talent_store.get_candidate(c), store)  # type: ignore[arg-type]

    cand_a = talent_store.get_candidate(a)
    similar = talent_graph.find_similar_candidates(cand_a, store, limit=5)  # type: ignore[arg-type]
    ids = [m["candidate_id"] for m in similar]
    assert a not in ids
    assert b in ids


# --------------------------------------------------------------------------- #
# Reindex
# --------------------------------------------------------------------------- #

def test_reindex_all_upserts_active_drops_archived(db: Path) -> None:
    eid = _engagement()
    active = talent_store.upsert_candidate(engagement_id=eid, full_name="Active One")
    gone = talent_store.upsert_candidate(engagement_id=eid, full_name="Gone One")
    talent_store.archive_candidate(gone)

    store = RankingFakeStore()
    # Pre-seed a stale archived doc to prove reindex removes it.
    store.add_documents(
        ["stale"], [{"candidate_id": gone, "engagement_id": eid, "stage": "lead"}],
        [f"candidate-{gone}"], CANDIDATES_COLLECTION,
    )
    n = talent_graph.reindex_all(store)
    assert n == 1
    rows = store.collections[CANDIDATES_COLLECTION]
    ids = [r["metadata"]["candidate_id"] for r in rows]
    assert active in ids
    assert gone not in ids


# --------------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(db: Path) -> TestClient:
    app = FastAPI()
    app.include_router(talent_route.router)
    app.state.store = RankingFakeStore()
    return TestClient(app)


def test_matches_endpoint(client: TestClient, db: Path) -> None:
    eid = talent_store.upsert_engagement(
        role_title="VP Drilling", must_haves="offshore deepwater drilling"
    )
    # Create via the API so the route indexes into app.state.store.
    client.post("/candidates", json={
        "engagement_id": eid, "full_name": "Strong Fit",
        "current_title": "Offshore Deepwater Drilling Lead",
    })
    client.post("/candidates", json={
        "engagement_id": eid, "full_name": "Weak Fit",
        "current_title": "Treasury Analyst",
    })
    resp = client.get(f"/engagements/{eid}/matches?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body and body[0]["candidate_id"] is not None
    assert body[0]["score"] >= body[-1]["score"]


def test_matches_unknown_engagement_404(client: TestClient) -> None:
    assert client.get("/engagements/9999/matches").status_code == 404


def test_similar_endpoint_excludes_self(client: TestClient, db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="VP Drilling")
    a = client.post("/candidates", json={
        "engagement_id": eid, "full_name": "Alpha", "current_title": "Drilling Engineer",
    }).json()["id"]
    client.post("/candidates", json={
        "engagement_id": eid, "full_name": "Beta", "current_title": "Drilling Engineer",
    })
    resp = client.get(f"/candidates/{a}/similar?limit=5")
    assert resp.status_code == 200
    assert a not in [m["candidate_id"] for m in resp.json()]


def test_reindex_endpoint(client: TestClient, db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="VP Drilling")
    talent_store.upsert_candidate(engagement_id=eid, full_name="Direct Insert")
    resp = client.post("/talent/reindex")
    assert resp.status_code == 200
    assert resp.json()["indexed"] == 1
