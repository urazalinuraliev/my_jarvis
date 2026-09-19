"""CrewAI adapter: bridges the Smart-Marketing-Assistant-Crew-AI repo into OpenExecutive.

The CrewAI repo exposes two multi-agent crews:

1. ``meeting_prep`` — research → industry analysis → strategy → briefing, driven
   by ``src/main.py`` (procedural Python, Exa + Xquik search tools).
2. ``instagram`` — market research → content strategy → visual creation →
   copywriting → final report, driven by ``src/instagram/crew.py`` (CrewBase +
   YAML config).

Both are wrapped behind :class:`CrewAIAdapter`, which exposes the uniform
``AgentAdapter.run(...)`` contract. The adapter is lazy: it only imports
``crewai`` (and the sibling repo) when ``run`` is actually invoked, so the
Executive package stays importable in environments where CrewAI is absent.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from openexecutive.integrations.adapters import AgentAdapter, AgentResult, make_result

logger = logging.getLogger(__name__)

# Path to the sibling CrewAI repo. Overridable via env for worktrees.
_CREW_REPO = Path(
    os.environ.get(
        "CREWAI_REPO_PATH",
        str(Path(__file__).resolve().parents[5] / "Smart-Marketing-Assistant-Crew-AI"),
    )
)


def _ensure_crewai_on_path() -> None:
    """Add the CrewAI repo ``src`` dir to sys.path so ``import agents`` works."""
    src_dir = _CREW_REPO / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _load_crewai():
    """Import crewai lazily; raise a clear error if the extra is missing."""
    try:
        import crewai  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "CrewAI integration requires the 'crewai' package. "
            "Install with: pip install crewai"
        ) from exc
    return crewai


class CrewAIAdapter(AgentAdapter):
    """Runs a named CrewAI crew and normalises its output."""

    name = "run_crew"
    description = (
        "Delegate a multi-agent marketing workflow to the integrated CrewAI crew "
        "(meeting prep research/briefing or Instagram content strategy). "
        "Use for research synthesis, competitive analysis, content calendars, "
        "or copywriting pipelines."
    )

    SUPPORTED_CREWS = ("meeting_prep", "instagram")

    def __init__(self, crew: str = "instagram") -> None:
        if crew not in self.SUPPORTED_CREWS:
            raise ValueError(
                f"Unknown crew {crew!r}; expected one of {self.SUPPORTED_CREWS}"
            )
        self.crew = crew

    async def run(self, *, task: str, context: str = "", **kwargs: Any) -> AgentResult:
        if self.crew == "meeting_prep":
            return await self._run_meeting_prep(task=task, context=context, **kwargs)
        return await self._run_instagram(task=task, context=context, **kwargs)

    # ------------------------------------------------------------------
    # meeting_prep crew (procedural Python)
    # ------------------------------------------------------------------
    async def _run_meeting_prep(
        self, *, task: str, context: str, **kwargs: Any
    ) -> AgentResult:
        _ensure_crewai_on_path()
        _load_crewai()
        from agents import MeetingPrepAgents  # type: ignore
        from tasks import MeetingPrepTask  # type: ignore

        participants = kwargs.get("participants") or "the meeting participants"
        meeting_context = context or task
        objective = kwargs.get("objective") or "prepare for the meeting"

        agent_factory = MeetingPrepAgents()
        task_factory = MeetingPrepTask()

        research_agent = agent_factory.research_agent()
        industry_agent = agent_factory.industry_analysis_agent()
        strategy_agent = agent_factory.meeting_strategy_agent()
        briefing_agent = agent_factory.summary_and_briefing_agent()

        research_task = task_factory.research_task(research_agent, participants, meeting_context)
        industry_task = task_factory.industry_analysis_task(industry_agent, participants, meeting_context)
        strategy_task = task_factory.meeting_strategy_task(strategy_agent, meeting_context, objective)
        briefing_task = task_factory.summary_and_briefing_task(briefing_agent, meeting_context, objective)

        # Enforce the pipeline order the original main.py documents:
        # research + industry run in parallel, strategy depends on both,
        # briefing depends on all three.
        research_task.context = []
        industry_task.context = []
        strategy_task.context = [research_task, industry_task]
        briefing_task.context = [research_task, industry_task, strategy_task]

        from crewai import Crew

        crew = Crew(
            agents=[research_agent, industry_agent, strategy_agent, briefing_agent],
            tasks=[research_task, industry_task, strategy_task, briefing_task],
            verbose=True,
        )
        result = crew.kickoff()
        text = str(result)
        return make_result(
            text,
            consulted_specialists=["cso", "cmo"],
            metadata={"crew": "meeting_prep", "participants": participants},
        )

    # ------------------------------------------------------------------
    # instagram crew (CrewBase + YAML)
    # ------------------------------------------------------------------
    async def _run_instagram(
        self, *, task: str, context: str, **kwargs: Any
    ) -> AgentResult:
        _ensure_crewai_on_path()
        _load_crewai()
        # CrewBase resolves config paths relative to the crew module's __file__,
        # so the instagram package must be importable as-is.
        from instagram.crew import InstagramCrew  # type: ignore

        crew = InstagramCrew()
        # Inject runtime variables into the task descriptions via the same
        # {variable} placeholders the YAML configs declare.
        runtime_vars = {
            "current_date": kwargs.get("current_date", ""),
            "instagram_description": context or task,
            "topic_of_the_week": task,
        }
        
        # kickoff_async ni ishlatamiz va uni natijasini olib qaytaramiz
        result = await crew.crew().kickoff_async(inputs=runtime_vars)
        text = str(result)
        
        artifacts = [
            {"name": "market_research.md", "path": "market_research.md"},
            {"name": "visual-content.md", "path": "visual-content.md"},
            {"name": "final-content-strategy.md", "path": "final-content-strategy.md"},
        ]
        return make_result(
            text,
            artifacts=artifacts,
            consulted_specialists=["cmo"],
            metadata={"crew": "instagram", "topic": task},
        )


def get_crewai_adapter(crew: str = "instagram") -> CrewAIAdapter:
    """Factory used by the skill-tool layer to build a CrewAI adapter."""
    return CrewAIAdapter(crew=crew)