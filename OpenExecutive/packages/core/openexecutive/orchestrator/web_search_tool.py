"""Anthropic native server-side web search tool.

The `web_search_20250305` tool is executed by the Anthropic API itself — no
client-side handler is needed. The model issues `server_tool_use` blocks
during a generation and the API returns `web_search_tool_result` blocks
inline; both must be preserved in the assistant turn echoed back on the
next iteration so the model retains context for what it searched.

Because the block carries a `type` field instead of an `input_schema`, it
cannot be cached the way client-side tools are. The Executive keeps it
separate from the alphabetically-sorted client-tool list so the
`cache_control` marker stays on a real client tool.
"""
from __future__ import annotations

from typing import Any

from openexecutive.config import get_settings

WEB_SEARCH_TOOL_NAME = "web_search"


def build_web_search_tool() -> dict[str, Any] | None:
    """Return the Anthropic web_search tool dict, or None when disabled.

    Read at tool-list assembly time (per turn) so toggling the env var
    without a restart takes effect on the next turn.
    """
    settings = get_settings()
    if not settings.enable_web_search:
        return None

    tool: dict[str, Any] = {
        "type": "web_search_20250305",
        "name": WEB_SEARCH_TOOL_NAME,
        "max_uses": settings.web_search_max_uses,
    }
    if settings.web_search_allowed_domains:
        tool["allowed_domains"] = settings.web_search_allowed_domains
    if settings.web_search_blocked_domains:
        tool["blocked_domains"] = settings.web_search_blocked_domains
    return tool
