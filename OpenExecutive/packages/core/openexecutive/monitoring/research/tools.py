"""Anthropic tool spec the specialists emit research findings through.

The specialist's response must include exactly one
``emit_research_findings`` tool_use block — its ``findings`` array
carries the structured items. Whatever else the model emits (text,
web_search server-tool calls, web_search results) is ignored.
"""
from __future__ import annotations

from typing import Any

EMIT_RESEARCH_FINDINGS_TOOL: dict[str, Any] = {
    "name": "emit_research_findings",
    "description": (
        "Report your research findings to the Executive. Call this "
        "EXACTLY ONCE with your full list of findings for this run. "
        "Each finding is a self-contained observation the Executive "
        "will read and decide what to do with — DM a Person, message "
        "a department, surface as a briefing card, add to the "
        "watchlist for ongoing monitoring, schedule a follow-up, or "
        "ignore. You do not route them yourself; you surface what "
        "matters in your domain."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "description": (
                    "Cap your list at the per-specialist limit named "
                    "in your task instructions. Prefer fewer "
                    "high-signal findings over many low-signal ones — "
                    "an empty list is the right answer when nothing in "
                    "your domain warrants the Executive's attention."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": (
                                "Short headline (no period). Becomes "
                                "the subject of any DM or briefing "
                                "card the Executive routes from this."
                            ),
                        },
                        "summary": {
                            "type": "string",
                            "description": (
                                "1-3 sentences. Quote the source on "
                                "critical numbers / dates / names "
                                "rather than paraphrasing."
                            ),
                        },
                        "severity_hint": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                            "description": (
                                "Your read on the impact. 'urgent' is "
                                "reserved for things needing action "
                                "within 24h; everything else "
                                "calibrates against general "
                                "alert-pipeline severity."
                            ),
                        },
                        "suggested_audience": {
                            "type": "string",
                            "description": (
                                "Soft routing hint. One of: "
                                "'principal' (DM the principal), "
                                "'department:<slug>' (e.g. "
                                "'department:marketing' — message the "
                                "dept channel or its head), "
                                "'watchlist' (worth adding to the "
                                "external-monitor watchlist for "
                                "ongoing tracking), "
                                "'workflow:<name>' (warrants a deeper "
                                "workflow — e.g. "
                                "'workflow:competitive_teardown'), "
                                "or 'noone' (log only). The Executive "
                                "may override."
                            ),
                        },
                        "suggested_action": {
                            "type": "string",
                            "description": (
                                "One concise sentence. Verifiable "
                                "next step the audience can take in "
                                "<15 min."
                            ),
                        },
                        "relevant_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "URLs you verified via web_search. "
                                "The Executive cites these on the "
                                "outgoing message so the audience "
                                "can verify in one click."
                            ),
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": (
                                "'high' = verified via web_search "
                                "AND directly tied to a company-"
                                "specific signal. 'medium' = one "
                                "uncertain. 'low' = both uncertain — "
                                "usually skip."
                            ),
                        },
                    },
                    "required": [
                        "title",
                        "summary",
                        "severity_hint",
                        "suggested_audience",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["findings"],
    },
}


__all__ = ["EMIT_RESEARCH_FINDINGS_TOOL"]
