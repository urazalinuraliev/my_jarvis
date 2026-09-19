"""Base classes for external-framework agent adapters.

An ``AgentAdapter`` translates a framework-specific agent graph into the
uniform ``run(...) -> AgentResult`` contract that the Executive's skill-tool
layer understands. This keeps the orchestration loop framework-agnostic: the
Executive never imports crewai/langgraph directly, it only talks to adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Structured output returned by every adapter."""

    text: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    consulted_specialists: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentAdapter:
    """Minimal interface every framework adapter implements."""

    name: str = "agent"
    description: str = "Runs an external multi-agent workflow."

    async def run(self, *, task: str, context: str = "", **kwargs: Any) -> AgentResult:
        raise NotImplementedError

    def tool_spec(self) -> dict[str, Any]:
        """Return the Anthropic tool schema advertising this adapter."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The marketing or research task to delegate to the crew.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional conversation/company context the crew should consider.",
                    },
                },
                "required": ["task"],
            },
        }


def make_result(
    text: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    consulted_specialists: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentResult:
    return AgentResult(
        text=text,
        artifacts=artifacts or [],
        consulted_specialists=consulted_specialists or [],
        metadata=metadata or {},
    )