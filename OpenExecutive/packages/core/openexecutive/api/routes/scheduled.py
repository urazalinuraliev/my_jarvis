"""Admin endpoints for inspecting and cancelling proactive scheduled actions."""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from openexecutive.config import get_settings
from openexecutive.memory.episodic import (
    ScheduledAction,
    cancel_scheduled_action,
    get_scheduled_action,
    list_scheduled_actions,
)

router = APIRouter()
logger = logging.getLogger(__name__)


_VALID_STATUS_FILTERS = {"pending", "running", "done", "failed", "cancelled"}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_admin_token(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Gate destructive scheduled-action endpoints. Fails closed by default.

    Three cases:
    - SCHEDULED_ADMIN_TOKEN is set → must match the header (constant-time compare).
    - SCHEDULED_ADMIN_TOKEN is unset and request comes from loopback → allowed
      (convenient for `make dev`).
    - SCHEDULED_ADMIN_TOKEN is unset and request comes from a remote host → 503,
      forcing operators to set the token before exposing the endpoint.

    Applied only to DELETE (cancel) — GETs are unauthenticated to match the
    /memories/* routes the Memories UI already consumes.
    """
    expected = get_settings().scheduled_admin_token
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in _LOOPBACK_HOSTS

    if expected:
        if x_admin_token is None or not hmac.compare_digest(
            x_admin_token, expected
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-Admin-Token",
            )
        return

    if not is_loopback:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Scheduled-action admin endpoints are disabled. Set "
                "SCHEDULED_ADMIN_TOKEN to enable them for non-loopback access."
            ),
        )


@router.get(
    "/scheduled",
    response_model=list[ScheduledAction],
)
def list_scheduled(
    status: str = "pending",
    limit: int = 100,
    order: str = "asc",
) -> list[ScheduledAction]:
    if status != "all" and status not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be 'all' or one of {sorted(_VALID_STATUS_FILTERS)}",
        )
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")
    return list_scheduled_actions(
        status=None if status == "all" else status,
        limit=limit,
        order=order,
    )


@router.get(
    "/scheduled/{action_id}",
    response_model=ScheduledAction,
)
def get_scheduled(action_id: int) -> ScheduledAction:
    row = get_scheduled_action(action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scheduled action not found")
    return row


@router.delete(
    "/scheduled/{action_id}",
    response_model=ScheduledAction,
    dependencies=[Depends(require_admin_token)],
)
def cancel_scheduled(action_id: int) -> ScheduledAction:
    result = cancel_scheduled_action(action_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="scheduled action not found")
    if result == "not_cancellable":
        raise HTTPException(
            status_code=409,
            detail="action is already running, done, failed, or cancelled — cannot cancel",
        )
    row = get_scheduled_action(action_id)
    if row is None:  # pragma: no cover — defensive
        raise HTTPException(status_code=404, detail="scheduled action not found")
    return row
