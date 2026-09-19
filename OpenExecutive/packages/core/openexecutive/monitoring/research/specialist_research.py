"""Drive one specialist through a research-mode tool-use turn.

Reuses ``BaseAgent.analyze_with_tools`` so the provider-call shape —
system block + cache_control, model resolution, deep-reasoning kwargs —
lives in one place. Only the research-mode addendum and the
``emit_research_findings`` tool definition live here.
"""
from __future__ import annotations

import logging
from typing import Any

from openexecutive.agents.base import BaseAgent
from openexecutive.config import get_settings
from openexecutive.monitoring.research.models import ResearchFinding
from openexecutive.monitoring.research.prompts import research_addendum_for
from openexecutive.monitoring.research.tools import (
    EMIT_RESEARCH_FINDINGS_TOOL,
)
from openexecutive.orchestrator.web_search_tool import build_web_search_tool

logger = logging.getLogger(__name__)

# Web-searches can push a research call well past the chat-time 180s
# default; 300s is the defensive ceiling on a single specialist.
_RESEARCH_TIMEOUT_SECONDS = 300.0


async def research_one_specialist(
    specialist_slug: str,
    agent: BaseAgent,
    research_context: str,
) -> list[ResearchFinding]:
    """Run one specialist through a research-mode turn. Returns the
    parsed findings (may be empty).

    Failures are caught + logged + returned as empty so the workflow's
    asyncio.gather doesn't abort on one specialist's crash. The
    workflow records per-specialist outcomes separately for the artifact.
    """
    settings = get_settings()
    if settings.research_agentic_scrape_enabled and settings.xcrawl_enabled:
        # Read-before-cite: the specialist runs a search→scrape_url→emit
        # loop so it grounds claims in full sources it actually read. Local
        # import avoids a module-load cycle (agentic imports _extract_findings
        # from here). Single-shot path below is unchanged when disabled.
        from openexecutive.monitoring.research.agentic import (
            run_specialist_agentic,
        )
        return await run_specialist_agentic(
            specialist_slug, agent, research_context,
        )

    from openexecutive.agents.research_council import (
        get_research_model,
        get_research_use_deep_reasoning,
    )

    tools: list[dict[str, Any]] = [EMIT_RESEARCH_FINDINGS_TOOL]
    web_search = build_web_search_tool()
    if web_search is not None:
        tools.append(web_search)

    # The research-mode turn is retrieve-from-web-search + summarize, not
    # deep strategic reasoning. Its model + deep-reasoning are controlled by
    # the `research` virtual agent in the Agent Council (Council override →
    # RESEARCH_MODEL env → cheap default), decoupled from each specialist's
    # chat-time Opus tier so a chat-quality bump can't re-inflate research
    # cost. Pinned per-call via analyze_with_tools' overrides; the agent's
    # chat-path defaults are untouched.
    try:
        message = await agent.analyze_with_tools(
            research_context,
            tools=tools,
            system_addendum=research_addendum_for(specialist_slug),
            timeout_seconds=_RESEARCH_TIMEOUT_SECONDS,
            model_override=get_research_model(),
            deep_reasoning_override=get_research_use_deep_reasoning(),
        )
    except Exception:
        logger.exception(
            "research: specialist=%s provider call failed", specialist_slug,
        )
        return []

    return _extract_findings(message, specialist_slug)


def _extract_findings(
    message: Any, specialist_slug: str,
) -> list[ResearchFinding]:
    """Find the ``emit_research_findings`` tool_use block and parse its
    findings array.

    Anthropic responses interleave text / tool_use / server_tool_use
    (web_search) / web_search_tool_result blocks. We only honor the
    FIRST ``emit_research_findings`` call (the tool description says
    "exactly once"; a second usually means model retry / hallucination
    loop and double-counting would inflate downstream weighting).
    """
    content = getattr(message, "content", None) or []
    raw_findings: list[dict[str, Any]] = []
    seen_emit_tool = False
    for block in content:
        if getattr(block, "type", "") != "tool_use":
            continue
        if getattr(block, "name", "") != "emit_research_findings":
            continue
        if seen_emit_tool:
            logger.warning(
                "research: specialist=%s emitted >1 emit_research_findings "
                "call — ignoring the extras", specialist_slug,
            )
            break
        seen_emit_tool = True
        block_input = getattr(block, "input", None) or {}
        items = block_input.get("findings")
        if isinstance(items, list):
            raw_findings.extend(items)

    if not raw_findings:
        # Empty research is a valid answer ("nothing in my domain
        # worth surfacing today") — log a debug, not a warning.
        logger.debug(
            "research: specialist=%s emitted no findings", specialist_slug,
        )
        return []

    parsed: list[ResearchFinding] = []
    for raw in raw_findings:
        try:
            finding = ResearchFinding(
                **raw,
                source_specialist=specialist_slug,
            )
        except Exception:
            logger.warning(
                "research: specialist=%s emitted malformed finding: %r",
                specialist_slug, raw,
            )
            continue
        parsed.append(finding)
    return parsed


__all__ = ["research_one_specialist"]
