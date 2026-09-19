"""FastAPI routes for the talent / executive-search core.

Surfaces CRUD for the two entities — engagements (searches we're hiring for in
this company) and candidates — mirroring the shape of ``api.routes.people``. All
rows live in the shared ``episodic_memory.db`` via ``openexecutive.talent.store``.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from openexecutive.talent import graph as talent_graph
from openexecutive.talent import offers as talent_offers
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import (
    Candidate,
    CandidateStage,
    Engagement,
    EngagementStatus,
    Offer,
    OfferStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_store(request: Request):  # type: ignore[return]
    """Resolve the warm ChromaDB store from app state, else build one.

    Mirrors ``api.routes.knowledge._get_store`` so the talent graph reuses the
    single in-process vector store the rest of the app shares.
    """
    if hasattr(request.app.state, "store"):
        return request.app.state.store
    from openexecutive.config import get_settings
    from openexecutive.knowledge.store import ChromaDBStore

    return ChromaDBStore(persist_directory=get_settings().vector_store_path)

# Field length bounds. Short = names/titles/locations/comp bands/department;
# long = role descriptions, must-haves, and candidate notes that may carry a
# pasted CV blurb.
_SHORT_MAX = 200
_LONG_MAX = 8000


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #

class EngagementCreate(BaseModel):
    role_title: str = Field(min_length=1, max_length=_SHORT_MAX)
    department: str = Field(default="", max_length=_SHORT_MAX)
    status: EngagementStatus = EngagementStatus.OPEN
    location: str = Field(default="", max_length=_SHORT_MAX)
    comp_band: str = Field(default="", max_length=_SHORT_MAX)
    must_haves: str = Field(default="", max_length=_LONG_MAX)
    description: str = Field(default="", max_length=_LONG_MAX)


class EngagementPatch(BaseModel):
    role_title: str | None = Field(default=None, min_length=1, max_length=_SHORT_MAX)
    department: str | None = Field(default=None, max_length=_SHORT_MAX)
    status: EngagementStatus | None = None
    location: str | None = Field(default=None, max_length=_SHORT_MAX)
    comp_band: str | None = Field(default=None, max_length=_SHORT_MAX)
    must_haves: str | None = Field(default=None, max_length=_LONG_MAX)
    description: str | None = Field(default=None, max_length=_LONG_MAX)


class CandidateCreate(BaseModel):
    engagement_id: int
    full_name: str = Field(min_length=1, max_length=_SHORT_MAX)
    current_title: str = Field(default="", max_length=_SHORT_MAX)
    current_company: str = Field(default="", max_length=_SHORT_MAX)
    location: str = Field(default="", max_length=_SHORT_MAX)
    email: str | None = None
    linkedin_url: str | None = None
    source: str = Field(default="", max_length=_SHORT_MAX)
    stage: CandidateStage = CandidateStage.LEAD
    notes: str = Field(default="", max_length=_LONG_MAX)


class CandidatePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=_SHORT_MAX)
    current_title: str | None = Field(default=None, max_length=_SHORT_MAX)
    current_company: str | None = Field(default=None, max_length=_SHORT_MAX)
    location: str | None = Field(default=None, max_length=_SHORT_MAX)
    email: str | None = None
    linkedin_url: str | None = None
    source: str | None = Field(default=None, max_length=_SHORT_MAX)
    notes: str | None = Field(default=None, max_length=_LONG_MAX)


class StagePatch(BaseModel):
    stage: CandidateStage


class OfferCreate(BaseModel):
    candidate_id: int
    comp_summary: str = Field(min_length=1, max_length=_LONG_MAX)
    note: str = Field(default="", max_length=_LONG_MAX)


class OfferPatch(BaseModel):
    comp_summary: str | None = Field(default=None, min_length=1, max_length=_LONG_MAX)
    note: str | None = Field(default=None, max_length=_LONG_MAX)


class OfferExtend(BaseModel):
    expires_at: str | None = None
    expires_in_days: int = Field(default=7, ge=1, le=60)
    note: str | None = Field(default=None, max_length=_LONG_MAX)


class OfferDecision(BaseModel):
    decision: OfferStatus
    note: str | None = Field(default=None, max_length=_LONG_MAX)


# --------------------------------------------------------------------------- #
# Engagements
# --------------------------------------------------------------------------- #

@router.get("/engagements", response_model=list[Engagement])
def list_engagements(include_archived: bool = False) -> list[Engagement]:
    return talent_store.list_engagements(include_archived=include_archived)


@router.get("/engagements/{engagement_id}", response_model=Engagement)
def get_engagement(engagement_id: int) -> Engagement:
    engagement = talent_store.get_engagement(engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


@router.post(
    "/engagements", response_model=Engagement, status_code=status.HTTP_201_CREATED
)
def create_engagement(body: EngagementCreate) -> Engagement:
    eid = talent_store.upsert_engagement(
        role_title=body.role_title,
        department=body.department,
        status=body.status,
        location=body.location,
        comp_band=body.comp_band,
        must_haves=body.must_haves,
        description=body.description,
    )
    engagement = talent_store.get_engagement(eid)
    if engagement is None:
        raise HTTPException(status_code=500, detail="Engagement vanished after insert")
    return engagement


@router.patch("/engagements/{engagement_id}", response_model=Engagement)
def patch_engagement(engagement_id: int, body: EngagementPatch) -> Engagement:
    current = talent_store.get_engagement(engagement_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    # All engagement columns are NOT NULL; an omitted OR explicitly-null field
    # keeps the current value.
    talent_store.upsert_engagement(
        role_title=body.role_title if body.role_title is not None else current.role_title,
        department=body.department if body.department is not None else current.department,
        status=body.status if body.status is not None else current.status,
        location=body.location if body.location is not None else current.location,
        comp_band=body.comp_band if body.comp_band is not None else current.comp_band,
        must_haves=body.must_haves if body.must_haves is not None else current.must_haves,
        description=(
            body.description if body.description is not None else current.description
        ),
        engagement_id=engagement_id,
    )
    updated = talent_store.get_engagement(engagement_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Engagement vanished")
    return updated


@router.post(
    "/engagements/{engagement_id}/archive", status_code=status.HTTP_204_NO_CONTENT
)
def archive_engagement(engagement_id: int) -> Response:
    if talent_store.get_engagement(engagement_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    talent_store.archive_engagement(engagement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

@router.get("/candidates", response_model=list[Candidate])
def list_candidates(
    engagement_id: int | None = None,
    stage: CandidateStage | None = None,
    include_archived: bool = False,
) -> list[Candidate]:
    return talent_store.list_candidates(
        engagement_id=engagement_id, stage=stage, include_archived=include_archived
    )


@router.get("/candidates/{candidate_id}", response_model=Candidate)
def get_candidate(candidate_id: int) -> Candidate:
    candidate = talent_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post(
    "/candidates", response_model=Candidate, status_code=status.HTTP_201_CREATED
)
def create_candidate(body: CandidateCreate, request: Request) -> Candidate:
    if talent_store.get_engagement(body.engagement_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Engagement {body.engagement_id} not found"
        )
    cid = talent_store.upsert_candidate(
        engagement_id=body.engagement_id,
        full_name=body.full_name,
        current_title=body.current_title,
        current_company=body.current_company,
        location=body.location,
        email=body.email,
        linkedin_url=body.linkedin_url,
        source=body.source,
        stage=body.stage,
        notes=body.notes,
    )
    candidate = talent_store.get_candidate(cid)
    if candidate is None:
        raise HTTPException(status_code=500, detail="Candidate vanished after insert")
    talent_graph.index_candidate(candidate, _get_store(request))
    return candidate


@router.patch("/candidates/{candidate_id}", response_model=Candidate)
def patch_candidate(candidate_id: int, body: CandidatePatch, request: Request) -> Candidate:
    current = talent_store.get_candidate(candidate_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # NOT NULL columns keep their current value on omit/null. Only `email` and
    # `linkedin_url` are nullable in the schema, so for those an explicit JSON
    # null clears the field while an omitted field is preserved — distinguished
    # via the exclude_unset key set. `stage` is intentionally not patchable
    # here — use POST /candidates/{id}/stage.
    provided = body.model_dump(exclude_unset=True)
    talent_store.upsert_candidate(
        engagement_id=current.engagement_id,
        full_name=body.full_name if body.full_name is not None else current.full_name,
        current_title=(
            body.current_title if body.current_title is not None else current.current_title
        ),
        current_company=(
            body.current_company
            if body.current_company is not None
            else current.current_company
        ),
        location=body.location if body.location is not None else current.location,
        email=provided.get("email", current.email),
        linkedin_url=provided.get("linkedin_url", current.linkedin_url),
        source=body.source if body.source is not None else current.source,
        stage=current.stage,
        notes=body.notes if body.notes is not None else current.notes,
        candidate_id=candidate_id,
    )
    updated = talent_store.get_candidate(candidate_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Candidate vanished")
    talent_graph.index_candidate(updated, _get_store(request))
    return updated


@router.post("/candidates/{candidate_id}/stage", response_model=Candidate)
def set_candidate_stage(candidate_id: int, body: StagePatch, request: Request) -> Candidate:
    if talent_store.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    talent_store.set_candidate_stage(candidate_id, body.stage)
    updated = talent_store.get_candidate(candidate_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Candidate vanished")
    talent_graph.index_candidate(updated, _get_store(request))
    return updated


@router.post("/candidates/{candidate_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_candidate(candidate_id: int, request: Request) -> Response:
    if talent_store.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    talent_store.archive_candidate(candidate_id)
    talent_graph.remove_candidate(candidate_id, _get_store(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Offers
# --------------------------------------------------------------------------- #

# Maps OfferActionError codes to HTTP statuses. Lifecycle conflicts are 409s;
# a malformed expiry is the caller's input problem (400).
_OFFER_ERROR_STATUS = {
    "not_found": 404,
    "bad_expiry": 400,
    "bad_status": 409,
    "bad_transition": 409,
    "approval_rejected": 409,
    "approval_pending": 409,
}


def _offer_http_error(exc: talent_offers.OfferActionError) -> HTTPException:
    return HTTPException(
        status_code=_OFFER_ERROR_STATUS.get(exc.code, 400), detail=exc.message
    )


class OfferActionResponse(BaseModel):
    """An offer action's outcome: the offer plus what else happened."""

    offer: Offer
    approval_state: str = "none"
    nudges_scheduled: int = 0
    cancelled_nudges: int = 0
    side_effects: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.get("/offers", response_model=list[Offer])
def list_offers(
    candidate_id: int | None = None,
    engagement_id: int | None = None,
    status: OfferStatus | None = None,
    include_archived: bool = False,
) -> list[Offer]:
    return talent_store.list_offers(
        candidate_id=candidate_id,
        engagement_id=engagement_id,
        status=status,
        include_archived=include_archived,
    )


@router.get("/offers/{offer_id}", response_model=Offer)
def get_offer(offer_id: int) -> Offer:
    offer = talent_store.get_offer(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


@router.post("/offers", response_model=Offer, status_code=status.HTTP_201_CREATED)
def create_offer(body: OfferCreate) -> Offer:
    candidate = talent_store.get_candidate(body.candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=404, detail=f"Candidate {body.candidate_id} not found"
        )
    try:
        oid = talent_store.create_offer(
            candidate_id=body.candidate_id,
            engagement_id=candidate.engagement_id,
            comp_summary=body.comp_summary,
            note=body.note,
        )
    except ValueError as exc:
        # One open offer per candidate.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    offer = talent_store.get_offer(oid)
    if offer is None:
        raise HTTPException(status_code=500, detail="Offer vanished after insert")
    return offer


@router.patch("/offers/{offer_id}", response_model=Offer)
def patch_offer(offer_id: int, body: OfferPatch) -> Offer:
    current = talent_store.get_offer(offer_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    if current.status not in (OfferStatus.DRAFT, OfferStatus.PENDING_APPROVAL):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Offer is {current.status.value}; terms are only editable while "
                "draft/pending_approval"
            ),
        )
    talent_store.update_offer_terms(
        offer_id, comp_summary=body.comp_summary, note=body.note
    )
    updated = talent_store.get_offer(offer_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Offer vanished")
    return updated


@router.post("/offers/{offer_id}/extend", response_model=OfferActionResponse)
def extend_offer(offer_id: int, body: OfferExtend) -> OfferActionResponse:
    """Mark the offer extended (the principal sent it) and schedule expiry nudges."""
    try:
        result = talent_offers.extend_offer(
            offer_id,
            expires_at=body.expires_at,
            expires_in_days=body.expires_in_days,
            note=body.note,
        )
    except talent_offers.OfferActionError as exc:
        raise _offer_http_error(exc) from exc
    return OfferActionResponse(
        offer=result.offer,
        approval_state=result.approval_state,
        nudges_scheduled=len(result.nudge_action_ids),
        warnings=result.warnings,
    )


@router.post("/offers/{offer_id}/decision", response_model=OfferActionResponse)
def record_offer_decision(offer_id: int, body: OfferDecision) -> OfferActionResponse:
    """Record the offer's terminal outcome; 'accepted' places the candidate."""
    try:
        result = talent_offers.record_offer_decision(
            offer_id, body.decision, note=body.note
        )
    except talent_offers.OfferActionError as exc:
        raise _offer_http_error(exc) from exc
    return OfferActionResponse(
        offer=result.offer,
        cancelled_nudges=result.cancelled_nudges,
        side_effects=result.side_effects,
    )


@router.post("/offers/{offer_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_offer(offer_id: int) -> Response:
    if talent_store.get_offer(offer_id) is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    talent_store.archive_offer(offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Talent graph — semantic matching
# --------------------------------------------------------------------------- #

class CandidateMatch(BaseModel):
    candidate_id: int
    engagement_id: int
    stage: str
    score: float


class ReindexResult(BaseModel):
    indexed: int


@router.get("/engagements/{engagement_id}/matches", response_model=list[CandidateMatch])
def match_candidates(
    engagement_id: int, request: Request, limit: int = 10
) -> list[dict[str, Any]]:
    """Rank the candidate pool against this engagement's role + must-haves."""
    engagement = talent_store.get_engagement(engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return talent_graph.match_candidates_for_engagement(
        engagement, _get_store(request), limit=limit
    )


@router.get("/candidates/{candidate_id}/similar", response_model=list[CandidateMatch])
def similar_candidates(
    candidate_id: int, request: Request, limit: int = 5
) -> list[dict[str, Any]]:
    """Find candidates whose profile is closest to this one (self excluded)."""
    candidate = talent_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return talent_graph.find_similar_candidates(
        candidate, _get_store(request), limit=limit
    )


@router.post("/talent/reindex", response_model=ReindexResult)
def reindex_talent(request: Request) -> ReindexResult:
    """Rebuild the talent index from the store (upsert active, drop archived)."""
    indexed = talent_graph.reindex_all(_get_store(request))
    return ReindexResult(indexed=indexed)
