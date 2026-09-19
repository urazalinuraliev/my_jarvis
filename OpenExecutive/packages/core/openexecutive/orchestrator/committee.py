"""The Committee — adversarial review and revision of an Executive draft.

Flow: draft → 3 reviewers in parallel → 1 revision. Reviewers always include
one quality judge plus two domain reviewers picked from the specialists the
Executive actually consulted this turn. Single pass — no iteration.
"""
from __future__ import annotations

import asyncio
import logging

from openexecutive.orchestrator.committee_reviewers import (
    Critique,
    Reviewer,
    build_domain_reviewer,
    build_quality_reviewer,
)
from openexecutive.orchestrator.router import SPECIALIST_REGISTRY

logger = logging.getLogger(__name__)

# Fallback domain reviewers when the Executive consulted fewer than two
# specialists this turn. cso + cfo cover the broadest range of operator
# questions — they get pulled in for any thread that doesn't already route
# through them.
_DOMAIN_FALLBACK_ORDER = ("cso", "cfo")


class Committee:
    """Coordinator for adversarial review and the Executive revision pass."""

    def __init__(
        self,
        reviewer_model: str,
    ) -> None:
        self._reviewer_model = reviewer_model

    def select_reviewers(self, consulted: list[str]) -> list[Reviewer]:
        """Pick 3 reviewers: 1 quality judge + 2 domain reviewers.

        Domain picks are drawn from `consulted` in order, deduped, and
        with `triage` filtered out (it is meta-routing, not a domain).
        Padded with the fallback list when the Executive consulted fewer
        than two domain specialists.
        """
        reviewers: list[Reviewer] = [build_quality_reviewer(self._reviewer_model)]

        picked: list[str] = []
        for spec in consulted:
            if spec == "triage" or spec in picked:
                continue
            if spec not in SPECIALIST_REGISTRY:
                continue
            picked.append(spec)
            if len(picked) == 2:
                break

        for fallback in _DOMAIN_FALLBACK_ORDER:
            if len(picked) >= 2:
                break
            if fallback not in picked:
                picked.append(fallback)

        for spec in picked:
            reviewers.append(build_domain_reviewer(spec, self._reviewer_model))

        return reviewers

    async def review(
        self,
        user_message: str,
        draft: str,
        consulted: list[str],
        specialist_outputs: dict[str, str] | None = None,
    ) -> list[Critique]:
        """Run the selected reviewers in parallel. Always returns one Critique
        per reviewer — failures degrade to low-severity placeholders inside
        Reviewer.critique."""
        reviewers = self.select_reviewers(consulted)
        logger.info(
            "committee.review reviewers=%s",
            [r.name for r in reviewers],
        )
        return list(
            await asyncio.gather(
                *(
                    r.critique(
                        user_message=user_message,
                        draft=draft,
                        specialist_outputs=specialist_outputs,
                    )
                    for r in reviewers
                )
            )
        )
