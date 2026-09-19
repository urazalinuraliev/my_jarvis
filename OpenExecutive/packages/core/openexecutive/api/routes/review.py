from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from openexecutive.knowledge.review_store import (
    Annotation,
    ContentType,
    Priority,
    ReviewItem,
    ReviewStatus,
    ReviewStore,
)

router = APIRouter(prefix="/review")


def _store() -> ReviewStore:
    from openexecutive.memory.episodic import DB_PATH

    return ReviewStore(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ReviewItemPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: ReviewStatus | None = None
    priority: Priority | None = None
    reviewer_notes: str | None = None


class BulkApproveRequest(BaseModel):
    domain: str | None = None


class BulkApproveResponse(BaseModel):
    approved_count: int


class AnnotationCreate(BaseModel):
    correction: str = Field(..., min_length=1)


class AnnotationPatch(BaseModel):
    correction: str | None = None
    is_active: bool | None = None


class ReviewStats(BaseModel):
    pending: int
    approved: int
    rejected: int
    needs_revision: int
    total: int


class ReviewItemDetail(BaseModel):
    """ReviewItem with its annotations included."""

    item: ReviewItem
    annotations: list[Annotation]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@router.get("/items", response_model=list[ReviewItem])
async def list_review_items(
    status: ReviewStatus | None = None,
    domain: str | None = None,
    content_type: ContentType | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ReviewItem]:
    return _store().list_items(
        status=status,
        domain=domain,
        content_type=content_type,
        limit=min(limit, 500),
        offset=offset,
    )


@router.get("/items/{item_id}", response_model=ReviewItemDetail)
async def get_review_item(item_id: str) -> ReviewItemDetail:
    store = _store()
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    annotations = store.list_annotations(item_id=item_id, active_only=False)
    return ReviewItemDetail(item=item, annotations=annotations)


@router.get("/stats", response_model=ReviewStats)
async def get_review_stats() -> ReviewStats:
    counts = _store().count_by_status()
    return ReviewStats(
        pending=counts.get("pending", 0),
        approved=counts.get("approved", 0),
        rejected=counts.get("rejected", 0),
        needs_revision=counts.get("needs_revision", 0),
        total=counts.get("total", 0),
    )


@router.patch("/items/{item_id}", response_model=ReviewItem)
async def update_review_item(item_id: str, body: ReviewItemPatch) -> ReviewItem:
    store = _store()
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    if body.status is not None:
        notes = body.reviewer_notes if body.reviewer_notes is not None else item.reviewer_notes
        item = store.set_status(item_id, body.status, notes)
    elif body.reviewer_notes is not None:
        # Notes-only update — use update_notes to avoid stomping reviewed_at
        item = store.update_notes(item_id, body.reviewer_notes)

    if body.priority is not None:
        item = store.set_priority(item_id, body.priority)

    return item


@router.post("/bulk-approve", response_model=BulkApproveResponse)
async def bulk_approve(body: BulkApproveRequest) -> BulkApproveResponse:
    count = _store().bulk_approve(domain=body.domain)
    return BulkApproveResponse(approved_count=count)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------


@router.get("/annotations", response_model=list[Annotation])
async def list_all_annotations(active_only: bool = True) -> list[Annotation]:
    return _store().list_annotations(active_only=active_only)


@router.get("/items/{item_id}/annotations", response_model=list[Annotation])
async def list_item_annotations(item_id: str) -> list[Annotation]:
    store = _store()
    if store.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return store.list_annotations(item_id=item_id, active_only=False)


@router.post("/items/{item_id}/annotations", response_model=Annotation)
async def add_annotation(item_id: str, body: AnnotationCreate) -> Annotation:
    store = _store()
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return store.add_annotation(item_id=item_id, domain=item.domain, correction=body.correction)


@router.patch("/annotations/{annotation_id}", response_model=dict[str, Any])
async def update_annotation(annotation_id: str, body: AnnotationPatch) -> dict[str, Any]:
    store = _store()
    if body.correction is not None:
        store.update_annotation(annotation_id, body.correction)
    if body.is_active is not None:
        store.toggle_annotation(annotation_id, body.is_active)
    return {"updated": annotation_id}


@router.delete("/annotations/{annotation_id}", response_model=dict[str, Any])
async def delete_annotation(annotation_id: str) -> dict[str, Any]:
    _store().delete_annotation(annotation_id)
    return {"deleted": annotation_id}
