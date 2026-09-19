"""Offer lifecycle actions shared by the chat tools and the /offers routes.

The ``offer_approval`` workflow drafts the package and pauses on a
``WaitForHumanEvent`` gate (HIRING_SIGNOFF approver). Paused runs never
auto-resume (generator resume is deferred upstream), so the
``pending_approval → extended`` transition is an explicit follow-up action:
:func:`extend_offer` consults the recorded gate resolution and performs the
transition. Centralizing it here — like ``talent.reminders`` centralizes the
recipient logic — means the chat tool and the HTTP route can't drift on the
approval/expiry semantics.

Expiry posture: :func:`extend_offer` schedules reminder nudges to the
*principal* (T−3d, T−1d, T+12h); a nudge never flips the offer's status —
only :func:`record_offer_decision` does, on the principal's say-so.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from openexecutive.talent import store as talent_store
from openexecutive.talent.models import (
    CandidateStage,
    EngagementStatus,
    Offer,
    OfferStatus,
)
from openexecutive.talent.reminders import resolve_reminder_context, schedule_reminder

logger = logging.getLogger(__name__)

ApprovalState = Literal["approved", "rejected", "pending", "none"]

# How far ahead of expiry the principal gets nudged, plus one past-expiry
# nudge so an offer can't silently sit expired with no decision recorded.
_NUDGE_OFFSETS: list[tuple[timedelta, str]] = [
    (timedelta(days=-3), "expires in 3 days"),
    (timedelta(days=-1), "expires tomorrow"),
    (timedelta(hours=12), "passed its expiry 12 hours ago"),
]

# How many recent offer_approval runs to scan PER STATUS when matching a gate
# to an offer. Bounded so the lookup stays O(small) on long-lived installs.
_APPROVAL_SCAN_LIMIT = 200

# Only these run statuses can carry a gate worth matching: a paused gate, a
# recorded resolution, or a timeout. Scanning per-status keeps failed/running
# runs (which have no usable state) from eating scan-window slots and pushing
# a recorded rejection out of reach.
_GATE_RUN_STATUSES = ("awaiting_human", "resolved", "timed_out")

_CONTEXT_PREFIX = "offer_id="


class OfferActionError(Exception):
    """A domain failure performing an offer action.

    ``code`` is machine-readable so the HTTP route can map it to a status
    code and the chat tool can surface it verbatim:
    ``not_found`` / ``bad_status`` / ``bad_expiry`` / ``approval_rejected``
    / ``bad_transition``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class OfferActionResult:
    """Outcome of an extend/decide action: the reloaded offer plus metadata."""

    offer: Offer
    approval_state: ApprovalState = "none"
    nudge_action_ids: list[int] = field(default_factory=list)
    cancelled_nudges: int = 0
    side_effects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def gate_context_summary(offer: Offer, candidate_name: str, role_title: str) -> str:
    """The machine-greppable context_summary the offer_approval gate carries.

    The ``offer_id=<n>`` prefix is what :func:`find_offer_approval` matches
    on — keep the prefix stable.
    """
    return (
        f"{_CONTEXT_PREFIX}{offer.id} — offer approval for {candidate_name} "
        f"({role_title})"
    )


def find_offer_approval(offer_id: int) -> dict[str, Any] | None:
    """Find the newest offer_approval gate run for this offer, if any.

    Matches the ``offer_id=<n>`` prefix embedded in the gate's
    ``context_summary`` (serialized into ``state_json``). Returns
    ``{run_id, status, decision, person_id}`` where ``decision`` is the
    parsed approve/reject/defer (or "" when unresolved), or None when no
    gate run references this offer.
    """
    from openexecutive.workflows import persistence

    runs: list[dict[str, Any]] = []
    for run_status in _GATE_RUN_STATUSES:
        runs.extend(
            persistence.list_runs(
                workflow_name="offer_approval",
                status=run_status,
                limit=_APPROVAL_SCAN_LIMIT,
            )
        )
    runs.sort(key=lambda r: str(r.get("updated_at", "")), reverse=True)
    for run in runs:  # newest-updated first
        full = persistence.get_run(run["run_id"])
        if full is None:
            continue
        state_raw = full.get("state_json")
        if not state_raw:
            continue
        try:
            state = json.loads(state_raw)
        except (ValueError, TypeError):
            continue
        summary = str(state.get("context_summary", ""))
        if not summary.startswith(f"{_CONTEXT_PREFIX}{offer_id} ") and (
            summary != f"{_CONTEXT_PREFIX}{offer_id}"
        ):
            continue
        decision = ""
        person_id = state.get("person_id")
        resolution_raw = full.get("resolution_json")
        if resolution_raw:
            try:
                resolution = json.loads(resolution_raw)
                decision = str(resolution.get("parsed_decision", {}).get("decision", ""))
                person_id = resolution.get("person_id", person_id)
            except (ValueError, TypeError):
                pass
        return {
            "run_id": run["run_id"],
            "status": full.get("status", ""),
            "decision": decision,
            "person_id": person_id,
        }
    return None


def offer_approval_state(offer_id: int) -> ApprovalState:
    """Roll the gate run for this offer up into one approval state.

    ``none`` = no gate run exists; ``pending`` = gate still awaiting (or the
    reply parsed to defer, or the run timed out without a decision).
    """
    found = find_offer_approval(offer_id)
    if found is None:
        return "none"
    if found["decision"] == "approve":
        return "approved"
    if found["decision"] == "reject":
        return "rejected"
    return "pending"


def _parse_expiry(
    expires_at: str | None, expires_in_days: int, now: datetime
) -> datetime:
    if expires_at:
        try:
            parsed = datetime.fromisoformat(expires_at)
        except ValueError as exc:
            raise OfferActionError(
                "bad_expiry", f"expires_at is not an ISO timestamp: {expires_at!r}"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed <= now:
            raise OfferActionError("bad_expiry", "expires_at must be in the future")
        return parsed
    return now + timedelta(days=expires_in_days)


def _nudge_text(offer: Offer, candidate_name: str, role_title: str, phase: str) -> str:
    return (
        f"Offer expiry reminder: the offer to {candidate_name} for the "
        f"{role_title} role (offer {offer.id}) {phase}. DM the principal so "
        f"they can check in with the candidate and either record a decision "
        f"(accepted / declined / expired) or re-extend. Do NOT contact the "
        f"candidate directly — this is a reminder for the principal."
    )


def extend_offer(
    offer_id: int,
    *,
    expires_at: str | None = None,
    expires_in_days: int = 7,
    note: str | None = None,
    has_principal_consent: bool = True,
) -> OfferActionResult:
    """Mark an offer extended (the principal sent it) and schedule expiry nudges.

    Consults the recorded approval-gate resolution: a ``reject`` blocks the
    extension; an ``approve`` stamps the run/approver onto the offer; pending
    or absent sign-off proceeds on the principal's explicit instruction
    (``has_principal_consent``, mirroring the authority gate's consent fast
    path) with the unrecorded sign-off flagged in ``warnings``.

    OE never sends the offer itself — this records that the principal
    extended it and queues the expiry reminders.

    Raises :class:`OfferActionError` on unknown offer, non-extensible status,
    bad expiry, or a recorded rejection.
    """
    offer = talent_store.get_offer(offer_id)
    if offer is None or offer.archived:
        raise OfferActionError("not_found", f"offer {offer_id} not found")
    if offer.status not in (OfferStatus.DRAFT, OfferStatus.PENDING_APPROVAL):
        raise OfferActionError(
            "bad_status",
            f"offer {offer_id} is {offer.status.value}; only draft/pending_approval "
            "offers can be extended",
        )

    approval = find_offer_approval(offer_id)
    approval_state = offer_approval_state(offer_id)
    if approval_state == "rejected":
        raise OfferActionError(
            "approval_rejected",
            f"the sign-off for offer {offer_id} was rejected "
            f"(run {approval['run_id'] if approval else '?'}); revise the offer "
            "or rescind it instead of extending",
        )
    warnings: list[str] = []
    if approval_state in ("pending", "none"):
        if not has_principal_consent:
            raise OfferActionError(
                "approval_pending",
                f"offer {offer_id} has no recorded sign-off "
                f"(approval state: {approval_state})",
            )
        warnings.append(
            "extended without a recorded HIRING_SIGNOFF approval "
            f"(approval state: {approval_state}) — proceeding on the principal's "
            "explicit instruction"
        )

    now = datetime.now(UTC)
    expiry_dt = _parse_expiry(expires_at, expires_in_days, now)

    # Expiry nudges go to the principal. Unreachable principal = extend
    # anyway, warn, schedule nothing — the digest still computes
    # "expiring soon" straight from expires_at.
    nudge_ids: list[int] = []
    candidate = talent_store.get_candidate(offer.candidate_id)
    candidate_name = candidate.full_name if candidate else f"candidate {offer.candidate_id}"
    engagement = talent_store.get_engagement(offer.engagement_id)
    role_title = engagement.role_title if engagement else "open"
    ctx = resolve_reminder_context(offer.candidate_id)
    if isinstance(ctx, str):
        warnings.append(f"no expiry reminders scheduled: {ctx}")
    else:
        for offset, phase in _NUDGE_OFFSETS:
            run_at = expiry_dt + offset
            if run_at <= now:
                continue
            nudge_ids.append(
                schedule_reminder(
                    ctx=ctx,
                    run_at=run_at,
                    intent_text=_nudge_text(offer, candidate_name, role_title, phase),
                )
            )

    changed = talent_store.set_offer_status(
        offer_id,
        OfferStatus.EXTENDED,
        expires_at=expiry_dt.isoformat(),
        approval_run_id=(approval or {}).get("run_id") if approval_state == "approved" else None,
        approved_by_person_id=(
            (approval or {}).get("person_id") if approval_state == "approved" else None
        ),
        nudge_action_ids=nudge_ids,
        note=note,
    )
    if not changed:
        # Lost a race (status changed between the read and the write).
        _cancel_nudges(nudge_ids)
        raise OfferActionError(
            "bad_transition", f"offer {offer_id} could not be extended (state changed)"
        )

    updated = talent_store.get_offer(offer_id)
    assert updated is not None
    return OfferActionResult(
        offer=updated,
        approval_state=approval_state,
        nudge_action_ids=nudge_ids,
        warnings=warnings,
    )


def record_offer_decision(
    offer_id: int,
    decision: OfferStatus,
    *,
    note: str | None = None,
) -> OfferActionResult:
    """Record the terminal outcome of an offer and clean up its nudges.

    ``accepted`` also moves the candidate to ``placed`` and the engagement to
    ``filled`` (documented side effects — PLACED coincides with FILLED).
    ``declined`` / ``expired`` / ``rescinded`` leave the candidate's stage
    untouched: the principal decides whether they go back to ``interviewed``
    or to ``rejected``.

    Raises :class:`OfferActionError` on unknown offer, a non-terminal
    ``decision`` value, or an illegal transition.
    """
    if decision not in (
        OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED, OfferStatus.RESCINDED
    ):
        raise OfferActionError(
            "bad_transition", f"decision must be terminal, got {decision.value!r}"
        )
    offer = talent_store.get_offer(offer_id)
    if offer is None or offer.archived:
        raise OfferActionError("not_found", f"offer {offer_id} not found")

    changed = talent_store.set_offer_status(offer_id, decision, note=note)
    if not changed:
        raise OfferActionError(
            "bad_transition",
            f"offer {offer_id} is {offer.status.value}; {decision.value} is not a "
            "legal transition from there",
        )

    cancelled = _cancel_nudges(offer.nudge_action_ids)

    side_effects: list[str] = []
    if decision is OfferStatus.ACCEPTED:
        if talent_store.set_candidate_stage(offer.candidate_id, CandidateStage.PLACED):
            side_effects.append(f"candidate {offer.candidate_id} moved to placed")
        if talent_store.set_engagement_status(offer.engagement_id, EngagementStatus.FILLED):
            side_effects.append(f"engagement {offer.engagement_id} marked filled")

    updated = talent_store.get_offer(offer_id)
    assert updated is not None
    return OfferActionResult(
        offer=updated,
        cancelled_nudges=cancelled,
        side_effects=side_effects,
    )


def _cancel_nudges(action_ids: list[int]) -> int:
    """Best-effort cancel of pending expiry nudges. Returns how many cancelled."""
    from openexecutive.memory.episodic import cancel_scheduled_action

    cancelled = 0
    for action_id in action_ids:
        try:
            if cancel_scheduled_action(action_id) == "cancelled":
                cancelled += 1
        except Exception:  # noqa: BLE001 — nudge cleanup must never block the decision
            logger.warning("offers: could not cancel nudge %s", action_id, exc_info=True)
    return cancelled


__all__ = [
    "ApprovalState",
    "OfferActionError",
    "OfferActionResult",
    "extend_offer",
    "find_offer_approval",
    "gate_context_summary",
    "offer_approval_state",
    "record_offer_decision",
]
