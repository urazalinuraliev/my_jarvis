"""Data models for the executive research workflow.

A ``ResearchFinding`` is what one specialist emits when its research
turns up something the Executive should know about. Findings are
deliberately ROUTING-AGNOSTIC at the specialist layer — the Executive's
synthesis pass decides per finding whether it warrants a DM to a Person,
a message to a department channel, an Alert in the briefing, a new
watchlist entry, a scheduled follow-up, or nothing. This mirrors how
``executive_reflection`` already operates on org-state signals: the
specialist surfaces context, the Executive picks the audience.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openexecutive.alerts.models import AlertSeverity

ConfidenceLevel = Literal["low", "medium", "high"]

# Suggested-audience hint values the specialists can emit. The Executive
# synthesis step treats these as soft guidance — it can override.
#   - 'principal'     → DM the principal
#   - 'department:<slug>' → message a department channel / its head
#   - 'watchlist'     → propose adding to the watchlist for ongoing watch
#   - 'workflow:<name>' → suggest invoking a deeper workflow (e.g. m&a_evaluation)
#   - 'noone'         → log only; not actionable yet
SUGGESTED_AUDIENCE_PRINCIPAL = "principal"
SUGGESTED_AUDIENCE_WATCHLIST = "watchlist"
SUGGESTED_AUDIENCE_NOONE = "noone"


class ResearchFinding(BaseModel):
    """One specialist's research finding.

    ``severity_hint`` lets the specialist convey "how urgent is this" so
    the Executive synthesis pass can lean toward DM-now vs. fold-into-
    briefing without needing to re-read the body. Same enum the alerts
    pipeline uses.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(
        ...,
        description=(
            "Short headline — one phrase, no period. Used as the "
            "subject line if the Executive routes via DM or alert."
        ),
    )
    summary: str = Field(
        ...,
        description=(
            "1-3 sentences. Quote the source where possible; don't "
            "paraphrase critical numbers / dates / names."
        ),
    )
    severity_hint: AlertSeverity = AlertSeverity.MEDIUM
    suggested_audience: str = Field(
        default=SUGGESTED_AUDIENCE_PRINCIPAL,
        description=(
            "Soft routing hint the Executive may follow or override. "
            "One of: 'principal', 'department:<slug>' (e.g. "
            "'department:marketing'), 'watchlist', 'workflow:<name>', "
            "or 'noone'."
        ),
    )
    suggested_action: str = Field(
        default="",
        description=(
            "One short sentence — the verifiable next step. e.g. "
            "'Update competitor battlecard before Friday's GTM sync.'"
        ),
    )
    relevant_urls: list[str] = Field(
        default_factory=list,
        description=(
            "Provenance — any URLs the specialist verified via "
            "web_search. The Executive cites these when routing."
        ),
    )
    confidence: ConfidenceLevel = "medium"
    source_specialist: str = Field(
        default="",
        description="Specialist slug (cso/cfo/...) that surfaced this. Set by the workflow.",
    )
    verification: str | None = Field(
        default=None,
        description=(
            "Set by the post-dedup verify pass (None when not verified): "
            "'confirmed' (source backs the claim), 'contradicted', "
            "'unsupported' (page doesn't support it), or "
            "'source_unreachable' (cited URL couldn't be scraped)."
        ),
    )


class ResearchRunSummary(BaseModel):
    """Per-specialist outcome of a research call — used in the artifact
    so the principal can see which specialists found what."""

    model_config = ConfigDict(extra="ignore")

    specialist: str
    findings_emitted: int
    error: str = ""


__all__ = [
    "ConfidenceLevel",
    "ResearchFinding",
    "ResearchRunSummary",
    "SUGGESTED_AUDIENCE_NOONE",
    "SUGGESTED_AUDIENCE_PRINCIPAL",
    "SUGGESTED_AUDIENCE_WATCHLIST",
]
