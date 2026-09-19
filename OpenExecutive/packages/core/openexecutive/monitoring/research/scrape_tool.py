"""The ``scrape_url`` client tool the research specialists use to READ a
full source page during research.

web_search gives specialists snippets — not enough to ground a claim. This
tool lets a specialist fetch the full clean markdown of an article it found
(via xcrawl, which renders JS + bypasses soft blocks) so it can verify the
exact dates / numbers / quotes before emitting a finding. Mirrors the
spec + ``handle_*`` pattern of ``orchestrator/alert_tools.py``.
"""
from __future__ import annotations

import logging
from typing import Any

from openexecutive.integrations import xcrawl_client

logger = logging.getLogger(__name__)

SCRAPE_URL_TOOL_NAME = "scrape_url"

# Chars of markdown fed back into the loop per scrape. xcrawl already caps
# the scrape at external_monitor_max_fetch_bytes; this further bounds the
# per-turn input tokens (≈ a few thousand) so a long article can't blow up
# the specialist's context across iterations.
_SCRAPE_RESULT_CHARS = 12_000

SCRAPE_URL_TOOL: dict[str, Any] = {
    "name": SCRAPE_URL_TOOL_NAME,
    "description": (
        "Fetch the full text (clean markdown) of a web page you found via "
        "web_search, so you can READ it and ground your finding's exact "
        "dates, numbers, and quotes in what the page actually says BEFORE "
        "you emit. Call this on the 1-3 most promising results before "
        "emit_research_findings. Pass a specific ARTICLE url (not a "
        "homepage or section link). Returns the page's main content as "
        "markdown, or an error string if it can't be read."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full http(s) URL of the article to read.",
            },
        },
        "required": ["url"],
    },
}


async def handle_scrape_url(
    tool_input: dict[str, Any], *, budget_remaining: int,
) -> str:
    """Execute one ``scrape_url`` call. Returns the page markdown, or a
    short instructive string the model can act on (no raise — a scrape
    miss must not break the specialist's turn).

    ``budget_remaining`` is the specialist's remaining scrape allowance;
    at or below zero the tool refuses and tells the model to emit.
    """
    if budget_remaining <= 0:
        return (
            "Scrape budget exhausted for this run — emit your findings now "
            "using what you have already read."
        )
    url = str((tool_input or {}).get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return "error: provide a full http(s) article URL."

    markdown = await xcrawl_client.scrape(url)
    if markdown is None:
        return (
            f"Could not read {url} (unreachable, blocked, or empty). Use a "
            "different source, or emit without it — do not cite a page you "
            "could not read."
        )
    return markdown[:_SCRAPE_RESULT_CHARS]


__all__ = ["SCRAPE_URL_TOOL", "SCRAPE_URL_TOOL_NAME", "handle_scrape_url"]
