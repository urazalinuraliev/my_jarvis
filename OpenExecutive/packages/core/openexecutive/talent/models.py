"""Pydantic models for the talent / executive-search core.

An ``Engagement`` is one search — a role we're hiring for in *this* company.
A ``Candidate`` is a person being considered for an engagement, moving through a
fixed pipeline. (The vertical is for in-house hiring: searches are run within the
company, not on behalf of external clients.)

These mirror the shape of ``openexecutive.people.models`` — plain Pydantic v2
models with an optional ``id`` (None before insert), ISO-string ``created_at`` /
``updated_at``, and an ``archived`` soft-delete flag.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EngagementStatus(StrEnum):
    """Lifecycle of one search engagement."""

    OPEN = "open"
    ON_HOLD = "on_hold"
    FILLED = "filled"
    CANCELLED = "cancelled"


class CandidateStage(StrEnum):
    """Pipeline stage of a candidate within an engagement.

    The order here is the intended forward progression; ``REJECTED`` is a
    terminal off-ramp reachable from any stage. ``PLACED`` is the terminal
    success state (and should coincide with the engagement moving to
    ``FILLED``).
    """

    LEAD = "lead"
    SCREENED = "screened"
    INTERVIEWED = "interviewed"
    OFFER = "offer"
    PLACED = "placed"
    REJECTED = "rejected"


class OfferStatus(StrEnum):
    """Lifecycle of an offer to a candidate.

    ``DRAFT`` → ``PENDING_APPROVAL`` → ``EXTENDED`` is the forward path;
    ``ACCEPTED`` / ``DECLINED`` / ``EXPIRED`` / ``RESCINDED`` are terminal.
    The ``pending_approval → extended`` transition is an explicit follow-up
    action (the ``extend_offer`` tool/route), never an automatic side effect
    of an approval resolution — workflow runs that pause on a human gate do
    not auto-resume (generator resume is deferred upstream).
    """

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    EXTENDED = "extended"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    RESCINDED = "rescinded"


OPEN_OFFER_STATUSES: frozenset[OfferStatus] = frozenset(
    {OfferStatus.DRAFT, OfferStatus.PENDING_APPROVAL, OfferStatus.EXTENDED}
)
TERMINAL_OFFER_STATUSES: frozenset[OfferStatus] = frozenset(
    {OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED, OfferStatus.RESCINDED}
)


class Engagement(BaseModel):
    """One search — a role we're hiring for in this company.

    ``department`` is an optional free-text in-house grouping (e.g. "Drilling");
    it is a plain label, not a FK to the departments entity. ``comp_band`` and
    ``location`` are free text — Phase 1 keeps them unstructured, matching how
    ``people`` started.
    """

    id: int | None = None
    role_title: str
    department: str = ""
    status: EngagementStatus = EngagementStatus.OPEN
    location: str = ""
    comp_band: str = ""
    must_haves: str = ""
    description: str = ""
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


class Candidate(BaseModel):
    """A person being considered for an engagement.

    ``engagement_id`` is a required FK — a candidate exists in the context of a
    specific search. ``fit_score`` (0-100) and ``screening_summary`` are
    populated by the ``candidate_screen`` workflow; they stay at their defaults
    (``None`` / "") until a screen runs.
    """

    id: int | None = None
    engagement_id: int
    full_name: str
    current_title: str = ""
    current_company: str = ""
    location: str = ""
    email: str | None = None
    linkedin_url: str | None = None
    source: str = ""
    stage: CandidateStage = CandidateStage.LEAD
    fit_score: int | None = Field(default=None, ge=0, le=100)
    screening_summary: str = ""
    notes: str = ""
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


class Offer(BaseModel):
    """An offer to a candidate on an engagement.

    A candidate has at most one *open* offer (draft / pending_approval /
    extended) at a time — terminal offers stay as history. ``package_md`` is
    the full offer-package artifact persisted by the ``offer_approval``
    workflow so the UI can render it after the run pauses on the approval
    gate. ``expires_at`` is set at extend time (not draft time); expiry never
    auto-flips the status — only ``record_offer_decision`` does.
    """

    id: int | None = None
    candidate_id: int
    engagement_id: int
    status: OfferStatus = OfferStatus.DRAFT
    comp_summary: str = ""
    package_md: str = ""
    note: str = ""
    expires_at: str | None = None
    extended_at: str = ""
    decided_at: str = ""
    approval_run_id: str = ""
    approved_by_person_id: int | None = None
    nudge_action_ids: list[int] = Field(default_factory=list)
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""
