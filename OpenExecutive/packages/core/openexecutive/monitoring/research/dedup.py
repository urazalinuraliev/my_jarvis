"""Lightweight cross-specialist finding dedup.

Two specialists looking at the same external event will sometimes
surface near-identical findings (CFO and CSO both notice a competitor's
funding round). We don't want the Executive synthesis pass to see the
same fact twice and double-act on it — but we also don't want to
over-merge and lose the per-specialist framing.

The dedup key is (lowercased title, lowercased first 80 chars of
summary). First-seen specialist keeps the framing; later proposers are
stamped onto the finding's source_specialist as comma-joined
attribution. The Executive sees consensus signal without redundant
items.
"""
from __future__ import annotations

import logging

from openexecutive.monitoring.research.models import ResearchFinding

logger = logging.getLogger(__name__)


def dedup_findings(
    findings_by_specialist: dict[str, list[ResearchFinding]],
) -> list[ResearchFinding]:
    """Collapse near-duplicate findings across specialists.

    Severity hint is promoted to the max across duplicates (consensus
    boosts urgency). Confidence is promoted similarly. ``source_specialist``
    becomes a comma-joined list so the Executive sees who flagged it.
    """
    by_key: dict[tuple[str, str], ResearchFinding] = {}
    rank_conf = {"low": 1, "medium": 2, "high": 3}
    rank_sev = {"low": 1, "medium": 2, "high": 3, "urgent": 4}

    for specialist, items in findings_by_specialist.items():
        for f in items:
            key = (
                (f.title or "").strip().lower(),
                (f.summary or "")[:80].strip().lower(),
            )
            existing = by_key.get(key)
            if existing is None:
                # Stamp source if specialist didn't fill it; the workflow
                # also stamps at parse time, but be defensive.
                stamped = f.model_copy(update={
                    "source_specialist": (
                        f.source_specialist or specialist
                    ),
                })
                by_key[key] = stamped
                continue
            # Duplicate — boost severity + confidence to the max of
            # the two, record additional specialist attribution.
            new_sev = (
                existing.severity_hint
                if rank_sev.get(existing.severity_hint.value, 0)
                >= rank_sev.get(f.severity_hint.value, 0)
                else f.severity_hint
            )
            new_conf = (
                existing.confidence
                if rank_conf.get(existing.confidence, 0)
                >= rank_conf.get(f.confidence, 0)
                else f.confidence
            )
            attribution = existing.source_specialist
            if specialist and specialist not in attribution.split(","):
                attribution = (
                    f"{attribution},{specialist}" if attribution else specialist
                )
            by_key[key] = existing.model_copy(update={
                "severity_hint": new_sev,
                "confidence": new_conf,
                "source_specialist": attribution,
            })

    return list(by_key.values())


__all__ = ["dedup_findings"]
