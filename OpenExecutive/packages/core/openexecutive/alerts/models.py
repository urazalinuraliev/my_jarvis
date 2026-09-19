from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


SEVERITY_RANK: dict[str, int] = {
    AlertSeverity.LOW.value: 0,
    AlertSeverity.MEDIUM.value: 1,
    AlertSeverity.HIGH.value: 2,
    AlertSeverity.URGENT.value: 3,
}


class AlertChannel(StrEnum):
    WEB = "web"
    SLACK_DM = "slack_dm"
    EMAIL = "email"
    PERSISTED = "persisted"
    # Shift 3 — broadcast channels. The triage agent picks these when the
    # alert is dept-scoped (no single human owner) or company-wide. The
    # dispatcher reads the accompanying TriageDecision.department_slug /
    # broadcast_integration fields to know which room to post to.
    DEPARTMENT_CHANNEL = "department_channel"
    COMPANY_BROADCAST = "company_broadcast"


class AlertEvent(BaseModel):
    """An external event that may or may not become an alert."""

    model_config = ConfigDict(extra="ignore")

    source: str  # "email" | "slack" | "document"
    external_id: str  # source-system id for idempotency
    subject: str = ""
    body: str = ""
    from_: str | None = Field(default=None, alias="from")
    channel: str | None = None
    user: str | None = None
    title: str | None = None  # for documents


class TriageDecision(BaseModel):
    """Structured output of the Triage agent."""

    model_config = ConfigDict(extra="ignore")

    alert: bool
    severity: AlertSeverity = AlertSeverity.LOW
    channels: list[AlertChannel] = Field(default_factory=list)
    headline: str = ""
    body: str = ""
    suggested_action: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    dedup_key: str = ""
    reason_if_suppressed: str = ""
    # Shift 3 broadcast routing. Set when `channels` contains
    # DEPARTMENT_CHANNEL or COMPANY_BROADCAST so the dispatcher knows
    # WHERE to post. Empty strings when the alert is per-person or
    # web-only — those channels never read these fields.
    department_slug: str = ""
    broadcast_integration: str = ""


class Alert(BaseModel):
    """A persisted alert row."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    external_id: str = ""
    source: str
    severity: str
    headline: str
    body: str
    suggested_action: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    channels_attempted: list[str] = Field(default_factory=list)
    channels_delivered: list[str] = Field(default_factory=list)
    dedup_key: str = ""
    status: str = "unread"  # unread | read | ack | dismissed
    created_at: str
    # Phase 4: person the alert is routed to for approval. NULL means the
    # alert is general (not routed to a specific approver).
    routed_to_person_id: int | None = None
    # Soft-delete for the Executive Artifacts gallery. NULL = active; an ISO
    # timestamp means the artifact was archived (hidden from the default list
    # but restorable). Only meaningful for source='artifact' rows.
    archived_at: str | None = None


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity_threshold: AlertSeverity = AlertSeverity.MEDIUM
    quiet_hours_start: str = ""  # "22:00"
    quiet_hours_end: str = ""  # "07:00"
    quiet_hours_tz: str = "UTC"
    channels_enabled: list[AlertChannel] = Field(
        default_factory=lambda: [
            AlertChannel.WEB,
            AlertChannel.SLACK_DM,
            AlertChannel.EMAIL,
            AlertChannel.PERSISTED,
        ]
    )


class MuteTopic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    pattern: str
    created_at: str


