"""Talent graph — semantic candidate matching over a ChromaDB collection.

Phase 2 of the talent platform. Candidates are indexed into a dedicated
``talent_candidates`` ChromaDB collection (separate from the knowledge/company
collections so candidate profiles never blend into RAG). Two queries are
exposed:

- ``match_candidates_for_engagement`` — rank the whole candidate pool against an
  engagement's role + must-haves (a cross-engagement talent pool, not just that
  engagement's own candidates).
- ``find_similar_candidates`` — given a candidate, find others like them.

Indexing is best-effort and called from the API layer after a talent-store
mutation (the store stays a pure SQLite layer). The ``KnowledgeStore``
``query`` interface only filters by ``domain``, so archived rows and the query
candidate itself are excluded by over-fetching and post-filtering, mirroring the
knowledge retriever.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openexecutive.talent import store as talent_store

if TYPE_CHECKING:
    from openexecutive.knowledge.store import KnowledgeStore
    from openexecutive.talent.models import Candidate, Engagement

logger = logging.getLogger(__name__)

CANDIDATES_COLLECTION = "talent_candidates"

# Over-fetch factor: post-filtering drops archived rows and (for similar) the
# query candidate itself, so ask Chroma for more than requested then slice.
_OVERFETCH = 3
_MAX_OVERFETCH = 50


def candidate_document(candidate: Candidate) -> str:
    """Build the searchable profile text indexed for a candidate.

    Joins the human-meaningful fields; the screening summary (when present)
    carries the richest signal so it is included. Empty fields are dropped so
    the embedding isn't diluted with blank labels.
    """
    parts = [
        candidate.full_name,
        candidate.current_title,
        candidate.current_company,
        candidate.location,
        candidate.source,
        candidate.notes,
        candidate.screening_summary,
    ]
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _metadata(candidate: Candidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "engagement_id": candidate.engagement_id,
        "stage": candidate.stage.value,
    }


def _doc_id(candidate_id: int) -> str:
    return f"candidate-{candidate_id}"


def index_candidate(candidate: Candidate, store: KnowledgeStore) -> None:
    """Upsert (or remove, if archived) one candidate in the talent index.

    Best-effort: a vector-store failure is logged and swallowed so candidate
    CRUD never fails because the index is unavailable. An archived candidate is
    removed from the index rather than indexed.
    """
    if candidate.id is None:
        return
    try:
        if candidate.archived:
            store.delete_documents(
                CANDIDATES_COLLECTION, {"candidate_id": candidate.id}
            )
            return
        text = candidate_document(candidate)
        if not text:
            # Nothing meaningful to embed — make sure no stale doc lingers.
            store.delete_documents(
                CANDIDATES_COLLECTION, {"candidate_id": candidate.id}
            )
            return
        store.add_documents(
            texts=[text],
            metadatas=[_metadata(candidate)],
            ids=[_doc_id(candidate.id)],
            collection=CANDIDATES_COLLECTION,
        )
    except Exception:  # noqa: BLE001 — index sync must never break CRUD
        logger.warning("talent.graph: failed to index candidate %s", candidate.id, exc_info=True)


def remove_candidate(candidate_id: int, store: KnowledgeStore) -> None:
    """Best-effort removal of a candidate from the talent index."""
    try:
        store.delete_documents(CANDIDATES_COLLECTION, {"candidate_id": candidate_id})
    except Exception:  # noqa: BLE001
        logger.warning("talent.graph: failed to remove candidate %s", candidate_id, exc_info=True)


def _score(distance: float | None) -> float:
    """Convert a cosine distance to a 0-1 similarity score (higher = closer).

    Cosine distance runs 0..2; anything past 1.0 (a genuinely poor match) is
    clamped to 0.0 — those candidates are not worth distinguishing.
    """
    if distance is None:
        return 0.0
    # Clamp BOTH ends: distance can be a tiny negative (float artifact on
    # near-identical vectors) → score just over 1.0, or > 1.0 → negative.
    return min(1.0, max(0.0, round(1.0 - distance, 4)))


def _result(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("metadata") or {}
    return {
        "candidate_id": meta.get("candidate_id"),
        "engagement_id": meta.get("engagement_id"),
        "stage": meta.get("stage"),
        "score": _score(row.get("distance")),
    }


def match_candidates_for_engagement(
    engagement: Engagement,
    store: KnowledgeStore,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank the candidate pool against an engagement's role + must-haves.

    Returns up to ``limit`` matches, each ``{candidate_id, engagement_id,
    stage, score}``, best first. Archived candidates are never in the index, so
    no archived filtering is needed beyond what indexing already guarantees.
    """
    if limit <= 0:
        return []
    query_text = "\n".join(
        p for p in (engagement.role_title, engagement.must_haves, engagement.description) if p
    ).strip()
    if not query_text:
        return []
    # No over-fetch needed: archived candidates are never in the index and
    # there is no self to exclude here, so the top `limit` rows are the answer.
    rows = store.query(
        query_text=query_text,
        collection=CANDIDATES_COLLECTION,
        n_results=min(limit, _MAX_OVERFETCH),
    )
    return [_result(r) for r in rows][:limit]


def find_similar_candidates(
    candidate: Candidate,
    store: KnowledgeStore,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find candidates similar to ``candidate``, excluding the candidate itself.

    Over-fetches and post-filters out the query candidate (Chroma would
    otherwise return it as the closest match to its own profile).
    """
    if limit <= 0:
        return []
    query_text = candidate_document(candidate)
    if not query_text:
        return []
    # +1 so dropping self still leaves room for `limit` others.
    n = min((limit + 1) * _OVERFETCH, _MAX_OVERFETCH)
    rows = store.query(
        query_text=query_text, collection=CANDIDATES_COLLECTION, n_results=n
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        result = _result(row)
        cid = result["candidate_id"]
        # Drop the query candidate itself, and any row missing an id (which
        # would spuriously match a None query id under ==).
        if cid is None or cid == candidate.id:
            continue
        out.append(result)
        if len(out) >= limit:
            break
    return out


def reindex_all(store: KnowledgeStore, db_path: Any = None) -> int:
    """Rebuild the talent index from the store. Returns the count indexed.

    Reconciles fully: every non-archived candidate is upserted (id-keyed, so
    updates land in place) and every archived candidate is removed. Because the
    talent store only soft-deletes, this covers every row that ever existed.
    """
    candidates = talent_store.list_candidates(include_archived=True, db_path=db_path)
    # `c.id is not None` keeps the three add_documents lists strictly aligned —
    # store-loaded rows always carry an int id, but the guard makes that
    # explicit rather than relying on it.
    active = [
        c for c in candidates
        if not c.archived and c.id is not None and candidate_document(c)
    ]
    archived = [c for c in candidates if c.archived]

    if active:
        store.add_documents(
            texts=[candidate_document(c) for c in active],
            metadatas=[_metadata(c) for c in active],
            ids=[_doc_id(c.id) for c in active],  # type: ignore[arg-type]
            collection=CANDIDATES_COLLECTION,
        )
    for cand in archived:
        if cand.id is not None:
            store.delete_documents(CANDIDATES_COLLECTION, {"candidate_id": cand.id})
    return len(active)
