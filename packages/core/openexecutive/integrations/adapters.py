"""Framework-agnostic contract for external multi-agent workflows.

An :class:`AgentAdapter` hides a third-party agent framework (CrewAI today)
behind a single async ``run(...) -> AgentResult`` call, so the orchestrator,
the CLI and the channel integrations never import the framework directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict


class OutputFile(TypedDict):
    """A file a workflow run wrote.

    Not to be confused with a workflow run's ``artifact`` — the Markdown
    deliverable stored on the run itself, which is ``AgentResult.text``.
    """

    name: str
    path: str


@dataclass
class AgentResult:
    """What one adapter run produced."""

    # The final deliverable, as text.
    text: str = ""
    # Files the run wrote (absolute server paths — keep them out of chats).
    files: list[OutputFile] = field(default_factory=list)
    # Keys of the OE specialists whose domain the run covered (for auditing).
    consulted_specialists: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentAdapter(ABC):
    """One external multi-agent workflow."""

    @abstractmethod
    async def run(self, *, task: str, context: str = "", **kwargs: Any) -> AgentResult:
        """Run the workflow on *task*, with optional background *context*."""
