"""Talent / executive-search pipeline digest for the briefing surfaces.

The talent vertical (in-house searches / candidates) shipped as a standalone
``/talent`` UI plus a set of workflows, but neither ``/today`` nor ``/chat`` knew
it existed. This module is the single rollup the two surfaces share, mirroring
``briefing/context.py`` (which does the same job for open alerts):

- :func:`build_talent_brief_items` → structured ``TalentBriefItem`` list rendered
  as a dedicated section on ``/today`` and the briefing UI.
- :func:`format_talent_for_prompt` → a compact one-line-per-engagement digest the
  chat route appends to the user-turn ``<briefing>`` block so the Executive can
  discuss live search progress.

Both read the same active engagements + their candidate pipelines and roll the
candidates up by stage, so the structured cards and the chat digest never
disagree. Every entry point swallows its own errors and returns an empty result
so a talent-store hiccup can never break a brief or a chat turn.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from openexecutive.talent.models import CandidateStage, EngagementStatus, OfferStatus

logger = logging.getLogger(__name__)

# A candidate counts as "stalled" once it has sat in a non-terminal stage this
# many days without an update. The search principal usually wants these surfaced
# first — they are the ones quietly going cold.
STALL_THRESHOLD_DAYS = 7

# Candidates in these stages are still in play; PLACED / REJECTED are terminal
# off-ramps and never count toward "stalled".
_ACTIVE_STAGES: frozenset[CandidateStage] = frozenset(
    {
        CandidateStage.LEAD,
        CandidateStage.SCREENED,
        CandidateStage.INTERVIEWED,
        CandidateStage.OFFER,
    }
)

# Cap how many engagements the brief / digest carries so a large book of
# business can't blow the /today payload or the per-turn token budget.
_MAX_ENGAGEMENTS = 25

# An extended offer counts as "expiring soon" once it is within this many
# hours of its expiry (or already past it without a recorded decision).
OFFER_EXPIRY_SOON_HOURS = 72


class TalentBriefItem(BaseModel):
    """One open search engagement, rolled up for the briefing surfaces.

    ``stage_counts`` maps each :class:`CandidateStage` value to the number of
    active (non-archived) candidates currently in it. ``needs_screening``
    (leads), ``offers_out`` (offers), and ``stalled_count`` are the three
    attention signals the UI badges and the narrative can lead with.
    """

    engagement_id: int
    role_title: str
    department: str = ""
    status: str
    location: str = ""
    candidate_count: int = 0
    stage_counts: dict[str, int] = Field(default_factory=dict)
    needs_screening: int = 0
    offers_out: int = 0
    # Extended offers whose expires_at is within OFFER_EXPIRY_SOON_HOURS (or
    # already past, with no decision recorded) — the most time-critical signal.
    offers_expiring_soon: int = 0
    stalled_count: int = 0


def _age_days(iso_ts: str, *, now: datetime) -> float | None:
    """Whole-and-fractional days between *iso_ts* and *now*, or None if unparseable."""
    if not iso_ts:
        return None
    try:
        parsed = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (now - parsed).total_seconds() / 86400.0


def build_talent_brief_items(
    db_path: Path | None = None,
    *,
    limit: int = _MAX_ENGAGEMENTS,
) -> list[TalentBriefItem]:
    """Roll active (open / on-hold) engagements up into briefing items.

    FILLED and CANCELLED engagements are dropped — the brief is about searches
    that still need attention. Returns ``[]`` on any failure (e.g. the talent
    tables don't exist yet on a fresh install) rather than raising, so callers
    never have to guard it.
    """
    from openexecutive.talent import store as talent_store

    try:
        engagements = talent_store.list_engagements(db_path=db_path)
    except Exception:
        logger.exception("talent_digest.list_engagements_failed")
        return []

    now = datetime.now(UTC)
    items: list[TalentBriefItem] = []

    for eng in engagements:
        if eng.status in (EngagementStatus.FILLED, EngagementStatus.CANCELLED):
            continue
        if eng.id is None:
            continue

        try:
            candidates = talent_store.list_candidates(engagement_id=eng.id, db_path=db_path)
        except Exception:
            logger.exception("talent_digest.list_candidates_failed engagement_id=%s", eng.id)
            candidates = []

        stage_counts: dict[str, int] = {}
        stalled = 0
        for cand in candidates:
            stage_counts[cand.stage.value] = stage_counts.get(cand.stage.value, 0) + 1
            if cand.stage in _ACTIVE_STAGES:
                age = _age_days(cand.updated_at, now=now)
                if age is not None and age >= STALL_THRESHOLD_DAYS:
                    stalled += 1

        items.append(
            TalentBriefItem(
                engagement_id=eng.id,
                role_title=eng.role_title,
                department=eng.department,
                status=eng.status.value,
                location=eng.location,
                candidate_count=len(candidates),
                stage_counts=stage_counts,
                needs_screening=stage_counts.get(CandidateStage.LEAD.value, 0),
                offers_out=stage_counts.get(CandidateStage.OFFER.value, 0),
                offers_expiring_soon=_count_expiring_offers(eng.id, now=now, db_path=db_path),
                stalled_count=stalled,
            )
        )

    # Most attention-worthy first: expiring offers, then offers out, then
    # stalled, then leads waiting to be screened, then larger pipelines.
    # Stable so ties keep store order.
    items.sort(
        key=lambda i: (
            i.offers_expiring_soon, i.offers_out, i.stalled_count,
            i.needs_screening, i.candidate_count,
        ),
        reverse=True,
    )
    return items[:limit]


def _count_expiring_offers(
    engagement_id: int, *, now: datetime, db_path: Path | None = None
) -> int:
    """Extended offers on this engagement within (or past) the expiry window.

    Computed straight from ``expires_at`` — a missed nudge can't make the
    digest go stale. Swallows failures to 0, like every rollup here.
    """
    from openexecutive.talent import store as talent_store

    try:
        offers = talent_store.list_offers(
            engagement_id=engagement_id, status=OfferStatus.EXTENDED, db_path=db_path
        )
    except Exception:
        logger.exception("talent_digest.list_offers_failed engagement_id=%s", engagement_id)
        return 0
    soon = 0
    for offer in offers:
        if not offer.expires_at:
            continue
        try:
            expiry = datetime.fromisoformat(offer.expires_at)
        except ValueError:
            continue
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if (expiry - now).total_seconds() <= OFFER_EXPIRY_SOON_HOURS * 3600:
            soon += 1
    return soon


def format_talent_for_prompt(
    db_path: Path | None = None,
    *,
    limit: int = _MAX_ENGAGEMENTS,
) -> str:
    """Render active engagements as a compact digest, or ``""`` when none.

    One line per engagement::

        [eng <id>] <role> [· <department>] (<status>): N candidates · M need
        screening · K offers out · S stalled >7d

    Pure synchronous reads — wrap in ``asyncio.to_thread`` at the call site.
    Never raises: any failure logs and returns ``""`` so a chat turn is never
    blocked by a talent-store hiccup.
    """
    items = build_talent_brief_items(db_path=db_path, limit=limit)
    if not items:
        return ""

    lines: list[str] = []
    for it in items:
        parts = [f"{it.candidate_count} candidate{'s' if it.candidate_count != 1 else ''}"]
        if it.needs_screening:
            parts.append(f"{it.needs_screening} need screening")
        if it.offers_out:
            parts.append(f"{it.offers_out} offer{'s' if it.offers_out != 1 else ''} out")
        if it.offers_expiring_soon:
            parts.append(
                f"{it.offers_expiring_soon} offer"
                f"{'s' if it.offers_expiring_soon != 1 else ''} expiring ≤3d"
            )
        if it.stalled_count:
            parts.append(f"{it.stalled_count} stalled >{STALL_THRESHOLD_DAYS}d")
        dept = f" · {it.department}" if it.department else ""
        lines.append(
            f"[eng {it.engagement_id}] {it.role_title}{dept} "
            f"({it.status}): " + " · ".join(parts)
        )

    header = (
        "Open searches we're hiring for in this company — the principal sees "
        "these as cards on /today. Each line is [eng <id>] role · department "
        "(status): pipeline rollup. When the user asks about a search by role, "
        "this is what they mean; use the talent tools to pull candidate detail."
    )
    return header + "\n" + "\n".join(lines)


__all__ = [
    "OFFER_EXPIRY_SOON_HOURS",
    "STALL_THRESHOLD_DAYS",
    "TalentBriefItem",
    "build_talent_brief_items",
    "format_talent_for_prompt",
]
