"""Open Executive as an MCP **server**.

This is the inverse of ``orchestrator/mcp_gateway.py`` (which lets the
Executive *consume* external MCP servers). Here we *expose* Open
Executive's company-grounded context and structured capabilities to
external MCP clients (Claude Desktop, Cursor, Claude Code, other agents)
over a Streamable-HTTP endpoint mounted at ``/mcp`` in the FastAPI app.

The value is not chat (OE already has six chat channels) — it is putting
OE's curated company state (resources) and its specialist council
(tools) *inside another agent's loop*.

Public surface:
- ``mcp``        — the configured ``FastMCP`` instance.
- ``mount``      — attach the Streamable-HTTP app to a FastAPI app.
- ``set_store`` / ``get_store`` — process-wide ChromaDB store handoff
  from the API lifespan, mirroring ``mcp_gateway.set_active_gateway``.
"""
from __future__ import annotations

from openexecutive.mcp_server.server import (
    get_store,
    mcp,
    mount,
    run_session_manager,
    set_store,
)

__all__ = ["get_store", "mcp", "mount", "run_session_manager", "set_store"]
