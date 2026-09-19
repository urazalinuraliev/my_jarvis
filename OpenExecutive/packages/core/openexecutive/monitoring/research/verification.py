"""Post-dedup verification of research findings against their cited source.

Research specialists discover via web_search (snippets — thin under
OpenRouter), but the finding contract demands verifying "URLs, dates,
names, and numbers against a current source" and findings "backed by a
dated URL you actually retrieved". The specialists have no way to
*retrieve* a page — only snippets. This pass closes that gap: for each
surviving finding it scrapes the cited URL (xcrawl, which renders JS and
bypasses soft blocks) and asks a cheap model whether the page actually
supports the claim, then adjusts confidence:

  - confirmed         → keep (page backs the claim)
  - contradicted      → confidence = low (dropped by the existing filter)
  - unsupported       → demote one notch (page doesn't support the claim)
  - source_unreachable→ demote one notch (cited URL couldn't be scraped —
                        the same hallucinated-URL failure mode as the watchlist)

Gated by ``xcrawl_enabled AND external_research_verify_enabled`` — a no-op
otherwise. Best-effort throughout: any scrape / LLM failure leaves the
finding unchanged so a verify hiccup can never sink a research run. Cost
is bounded: only findings with a cited URL, capped at
``research_verify_max_findings`` per run, on a cheap verify model.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from openexecutive.agents.base import BaseAgent
from openexecutive.alerts.models import SEVERITY_RANK
from openexecutive.config import get_settings
from openexecutive.integrations import xcrawl_client
from openexecutive.monitoring.research.models import (
    ConfidenceLevel,
    ResearchFinding,
)

logger = logging.getLogger(__name__)

# Scrape + one cheap LLM call; generous ceiling so a slow page can't hang
# the whole verify fan-out (each finding is independent under gather).
_VERIFY_TIMEOUT_SECONDS = 120.0
# Chars of scraped markdown fed to the verify model. xcrawl already caps the
# scrape at external_monitor_max_fetch_bytes; this bounds the verify call's
# input tokens (≈ a few thousand) regardless.
_MARKDOWN_CHARS = 12_000

# One-notch demotion. 'low' is terminal (the workflow's existing filter drops
# 'low' before synthesis).
_DEMOTE: dict[str, ConfidenceLevel] = {
    "high": "medium",
    "medium": "low",
    "low": "low",
}

_EMIT_VERIFICATION_NAME = "emit_verification"

EMIT_VERIFICATION_TOOL: dict[str, Any] = {
    "name": _EMIT_VERIFICATION_NAME,
    "description": (
        "Report whether the source page supports the research finding. "
        "Call this EXACTLY ONCE."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["confirmed", "contradicted", "unsupported"],
                "description": (
                    "'confirmed' — the page clearly states the finding's "
                    "specific claim (its dates / numbers / names / event). "
                    "'contradicted' — the page states something that "
                    "conflicts with the claim. 'unsupported' — the page does "
                    "not contain enough to support the specific claim (a "
                    "vaguely-related page is 'unsupported', not 'confirmed')."
                ),
            },
            "note": {
                "type": "string",
                "description": "≤1 sentence: the supporting/contradicting detail.",
            },
        },
        "required": ["verdict"],
    },
}

_VERIFY_SYSTEM = (
    "You verify one research finding against the full text of the single "
    "source page it cites. Decide ONLY from the provided page text — do not "
    "use outside knowledge — whether the page supports the finding's "
    "SPECIFIC claim (the dates, numbers, names, and event in its summary).\n\n"
    "Be strict: a page that is merely on the same topic but does not state "
    "the claim's specifics is 'unsupported', not 'confirmed'. Call "
    "emit_verification EXACTLY ONCE with your verdict."
)


class _VerifyAgent(BaseAgent):
    """Minimal agent shell so the pass can reuse ``analyze_with_tools`` (its
    provider resolution + system-block plumbing). Distinct ``name`` so it
    never collides with a real specialist's Council override; the model is
    pinned per call via ``model_override``."""

    name = "research_verify"
    domain = "utility"
    model = ""
    use_deep_reasoning = False

    def __init__(self) -> None:
        self.model = get_settings().research_verify_model

    def get_system_prompt(self) -> str:
        return _VERIFY_SYSTEM


def _first_url(finding: ResearchFinding) -> str | None:
    """First http(s) URL the finding cites, or None."""
    for raw in finding.relevant_urls:
        url = (raw or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    return None


def _demote(confidence: ConfidenceLevel) -> ConfidenceLevel:
    return _DEMOTE.get(confidence, confidence)


async def verify_findings(
    findings: list[ResearchFinding],
) -> list[ResearchFinding]:
    """Return ``findings`` with cited-source verification applied.

    Unchanged (no network) when xcrawl or verification is disabled, or when
    no finding cites a URL. Only the top ``research_verify_max_findings`` by
    severity (among those with a cited URL) are verified; the rest pass
    through untouched.
    """
    settings = get_settings()
    if not (settings.xcrawl_enabled and settings.external_research_verify_enabled):
        return findings

    cap = max(0, settings.research_verify_max_findings)
    # Only verify findings that (a) cite a URL and (b) could actually survive.
    # A finding already at 'low' confidence is dropped by the downstream
    # filter regardless of any verdict, so verifying it would waste a
    # scrape + LLM call AND let a doomed finding skew the confirmed/demoted
    # accounting (a 'low' demote is a no-op; a 'confirmed' low still drops).
    candidates = [
        (idx, f)
        for idx, f in enumerate(findings)
        if f.confidence != "low" and _first_url(f) is not None
    ]
    # Verify the highest-severity findings first so the budget protects the
    # ones most likely to be routed to a human.
    candidates.sort(
        key=lambda pair: SEVERITY_RANK.get(pair[1].severity_hint.value, 0),
        reverse=True,
    )
    selected = candidates[:cap]
    if not selected:
        return findings

    verdicts = await asyncio.gather(
        *(_verify_one(f) for _idx, f in selected),
        return_exceptions=True,
    )

    out = list(findings)
    confirmed = demoted = 0
    for (idx, original), result in zip(selected, verdicts, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "research verify: %r raised — leaving unchanged: %s",
                original.title[:80], result,
            )
            continue
        out[idx] = result
        if result.verification == "confirmed":
            confirmed += 1
        elif result.confidence != original.confidence:
            demoted += 1

    logger.info(
        "research verify: %d verified, %d confirmed, %d demoted",
        len(selected), confirmed, demoted,
    )
    return out


async def _verify_one(finding: ResearchFinding) -> ResearchFinding:
    """Verify one finding against its cited source. Returns a (possibly
    confidence-adjusted) copy with a ``verification`` tag set.

    An xcrawl *infra* failure (status ``error``) leaves the finding unchanged
    and untagged — a verify-pass outage must never demote a real finding. Only
    a page that is fetched-but-empty (a genuinely dead URL) is demoted to
    ``source_unreachable``. A genuine LLM error still propagates, which the
    caller treats as 'leave unchanged'."""
    url = _first_url(finding)
    if url is None:  # defensive; callers pre-filter
        return finding

    outcome = await xcrawl_client.scrape_detailed(url)
    if outcome.status in ("error", "disabled"):
        # Not a verdict on the source — xcrawl couldn't even be asked:
        #   error    — xcrawl itself failed (down / 401 / 429 / timeout)
        #   disabled — xcrawl off, OR enabled-but-no-key (the verify_findings
        #              gate only checks the enabled flag, not the key)
        # Demoting here would let a verify-pass outage or a config gap sink an
        # entire research run, exactly what this pass promises it never does.
        # Leave the finding untouched (and untagged, so the run's
        # verified-count reflects that we couldn't check it).
        return finding
    if outcome.markdown is None:
        # status == "empty": the page was fetched but yields no content — a
        # genuinely dead / unreadable source (the hallucinated-URL failure
        # mode this pass exists to catch).
        return finding.model_copy(update={
            "confidence": _demote(finding.confidence),
            "verification": "source_unreachable",
        })

    verdict = await _llm_verdict(finding, outcome.markdown[:_MARKDOWN_CHARS])
    if verdict == "confirmed":
        return finding.model_copy(update={"verification": "confirmed"})
    if verdict == "contradicted":
        return finding.model_copy(update={
            "confidence": "low", "verification": "contradicted",
        })
    if verdict == "unsupported":
        return finding.model_copy(update={
            "confidence": _demote(finding.confidence),
            "verification": "unsupported",
        })
    # verdict == "unknown" — model didn't return a usable verdict. Don't
    # penalize confidence for a verify miss, but tag it so the run's
    # verified-count reflects the attempt (vs. a finding we never touched).
    return finding.model_copy(update={"verification": "inconclusive"})


async def _llm_verdict(finding: ResearchFinding, markdown: str) -> str:
    """Return 'confirmed' | 'contradicted' | 'unsupported' | 'unknown'."""
    agent = _VerifyAgent()
    user_content = (
        f"<finding>\nTITLE: {finding.title}\nSUMMARY: {finding.summary}\n"
        f"</finding>\n\n<source_page>\n{markdown}\n</source_page>\n\n"
        "Does the source page support the finding's specific claim? "
        "Call emit_verification with your verdict."
    )
    message = await agent.analyze_with_tools(
        user_content,
        tools=[EMIT_VERIFICATION_TOOL],
        max_tokens=512,
        timeout_seconds=_VERIFY_TIMEOUT_SECONDS,
        model_override=get_settings().research_verify_model,
        deep_reasoning_override=False,
    )
    return _parse_verdict(message)


def _parse_verdict(message: Any) -> str:
    """Pull the verdict from the first emit_verification tool_use block;
    'unknown' when the model didn't emit a usable one."""
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", "") != "tool_use":
            continue
        if getattr(block, "name", "") != _EMIT_VERIFICATION_NAME:
            continue
        verdict = (getattr(block, "input", None) or {}).get("verdict")
        if verdict in ("confirmed", "contradicted", "unsupported"):
            return verdict
    return "unknown"


__all__ = ["EMIT_VERIFICATION_TOOL", "verify_findings"]
