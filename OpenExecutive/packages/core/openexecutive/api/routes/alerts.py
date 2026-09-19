from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openexecutive.alerts import store
from openexecutive.alerts.models import Alert

# The standalone alerts UI (panel, live toast stream, mute/severity settings,
# feedback) was removed — those items now surface only through the briefing
# (`/today`), which reads `store.list_alerts` directly. The alert ingestion →
# triage → storage pipeline is unchanged; this router only exposes the one
# endpoint the briefing still calls: acking a proposal to groom the queue.
router = APIRouter()


class AckBody(BaseModel):
    status: str = Field(..., pattern="^(read|ack|dismissed)$")


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
def ack_alert(alert_id: int, body: AckBody) -> Alert:
    if not store.set_status(alert_id, body.status):
        raise HTTPException(status_code=404, detail="Alert not found")
    updated = store.get_alert(alert_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return updated
