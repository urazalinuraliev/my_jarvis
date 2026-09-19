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

The crew repo is found via the ``CREWAI_REPO_PATH`` process env var, falling
back to a checkout next to this OpenExecutive checkout. Deployments without it
(e.g. the Fly image) report the crews as unavailable instead of failing
mid-run — see :func:`crew_unavailable_reason`.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openexecutive.integrations.adapters import AgentAdapter, AgentResult, make_result

logger = logging.getLogger(__name__)

SUPPORTED_CREWS: tuple[str, ...] = ("meeting_prep", "instagram")

_CREW_REPO_NAME = "Smart-Marketing-Assistant-Crew-AI"

# Markdown deliverables the Instagram crew writes into its run directory
# (the ``{output_dir}/...`` output_file paths in the crew's crew.py).
INSTAGRAM_OUTPUT_FILES: tuple[str, ...] = (
    "market_research.md",
    "visual-content.md",
    "final-content-strategy.md",
)


def _default_crew_repo() -> Path:
    # .../OpenExecutive/packages/core/openexecutive/integrations/crewai_adapter.py
    # → the directory that contains the OpenExecutive checkout.
    here = Path(__file__).resolve()
    parents = here.parents
    base = parents[5] if len(parents) > 5 else here.parent
    return base / _CREW_REPO_NAME


def crew_repo_path() -> Path:
    """Where the CrewAI repo lives: ``CREWAI_REPO_PATH`` or the sibling checkout."""
    configured = os.environ.get("CREWAI_REPO_PATH", "").strip()
    # A value starting with "#" is an inline .env comment that dotenv kept.
    if not configured or configured.startswith("#"):
        return _default_crew_repo()
    return Path(configured)


def crew_unavailable_reason() -> str | None:
    """Why the crews cannot run in this process, or ``None`` when they can.

    Cheap (a directory check and a module lookup, no imports), so it is safe
    to call at import time to decide whether to advertise the chat tool. The
    text names server paths: log it, don't show it to chat users.
    """
    repo = crew_repo_path()
    if not (repo / "src").is_dir():
        return (
            f"The CrewAI crew repo was not found at {repo}. Clone "
            f"{_CREW_REPO_NAME} next to the OpenExecutive checkout or set "
            "CREWAI_REPO_PATH."
        )
    if not (repo / "src" / "crew_llm.py").is_file():
        # An unmodified upstream clone: its crews neither take their model from
        # OE nor write into per-run directories.
        return (
            f"The CrewAI crew repo at {repo} is missing src/crew_llm.py, which "
            "this integration needs."
        )
    if find_spec("crewai") is None:
        return "The 'crewai' package is not installed (run `uv sync` in packages/core)."
    return None


def crew_integration_available() -> bool:
    return crew_unavailable_reason() is None


def resolve_crew_model(
    crewai_model: str | None, default_model: str, *, anthropic_direct: bool = True
) -> str | None:
    """The CrewAI model string for the crews' agents, or None if it must be configured.

    An explicit ``CREWAI_MODEL`` wins. Otherwise a bare Claude ``DEFAULT_MODEL``
    is reused on CrewAI's ``anthropic/`` provider — but only when OE itself
    sends it to Anthropic directly (``anthropic_direct``); with OpenRouter on,
    or the slug served by a local backend, calling Anthropic would bypass the
    operator's routing and key. Any other ``DEFAULT_MODEL`` is an OpenRouter or
    local slug that CrewAI would misroute (it reads a ``vendor/`` prefix as
    "call that vendor directly"), so it is not guessed either.
    """
    if crewai_model:
        return crewai_model
    if anthropic_direct and default_model.startswith("claude-"):
        return f"anthropic/{default_model}"
    return None


def _provider_api_key(settings: Any, model: str) -> str | None:
    """OE's key for the provider CrewAI will call for *model*, if OE has one."""
    if model.startswith(("anthropic/", "claude-")):
        return settings.anthropic_api_key  # type: ignore[no-any-return]
    if model.startswith("openrouter/"):
        return settings.openrouter_api_key  # type: ignore[no-any-return]
    return None


def _ensure_crew_repo_on_path() -> None:
    """Make the crew repo's top-level modules (agents, tasks, instagram) importable."""
    reason = crew_unavailable_reason()
    if reason is not None:
        raise RuntimeError(reason)
    src_dir = str(crew_repo_path() / "src")
    if src_dir not in sys.path:
        # Appended rather than prepended: the crew's module names are generic,
        # so they must never shadow an installed package of the same name.
        sys.path.append(src_dir)


def _configure_crew_llm() -> Any:
    """Hand the crews their model and API key in-process; return the settings.

    Passed through the crew repo's ``crew_llm.configure`` rather than exported
    as environment variables, so the key never reaches child processes that
    inherit this process's environment.
    """
    import crew_llm  # type: ignore[import-not-found]

    from openexecutive.config import get_settings
    from openexecutive.providers.registry import _local_models

    settings = get_settings()
    anthropic_direct = not settings.openrouter_enabled and (
        settings.default_model not in _local_models(settings)
    )
    model = resolve_crew_model(
        settings.crewai_model, settings.default_model, anthropic_direct=anthropic_direct
    )
    if model is None:
        raise RuntimeError(
            f"DEFAULT_MODEL={settings.default_model!r} is not served by Anthropic "
            "directly here (OpenRouter or local routing, or not a Claude model), so "
            "the CrewAI crews can't reuse it. Set CREWAI_MODEL to a CrewAI model "
            "string, e.g. anthropic/claude-sonnet-5 or openrouter/<model>."
        )
    crew_llm.configure(model=model, api_key=_provider_api_key(settings, model))
    # CrewAI ships anonymous usage telemetry on by default; keep it off unless
    # the operator opts in, matching the README's privacy promise.
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    return settings


def _new_run_dir(base: Path, crew: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = base / f"{stamp}-{crew}-{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True)
    return run_dir


class CrewAIAdapter(AgentAdapter):
    """Runs a named CrewAI crew and normalises its output."""

    name = "run_crew"
    description = (
        "Delegate a multi-agent marketing workflow to the integrated CrewAI crew "
        "(meeting prep research/briefing or Instagram content strategy). "
        "Use for research synthesis, competitive analysis, content calendars, "
        "or copywriting pipelines."
    )

    SUPPORTED_CREWS = SUPPORTED_CREWS

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
        _ensure_crew_repo_on_path()
        _configure_crew_llm()
        from agents import MeetingPrepAgents  # type: ignore[import-not-found]
        from crewai import Crew
        from tasks import MeetingPrepTask  # type: ignore[import-not-found]

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

        crew = Crew(
            agents=[research_agent, industry_agent, strategy_agent, briefing_agent],
            tasks=[research_task, industry_task, strategy_task, briefing_task],
            verbose=True,
        )
        # kickoff_async runs the (blocking) crew in a worker thread, so a
        # multi-minute pipeline never stalls the API's event loop.
        result = await crew.kickoff_async()
        return make_result(
            str(result),
            consulted_specialists=["cso", "cmo"],
            metadata={"crew": "meeting_prep", "participants": participants},
        )

    # ------------------------------------------------------------------
    # instagram crew (CrewBase + YAML)
    # ------------------------------------------------------------------
    async def _run_instagram(
        self, *, task: str, context: str, **kwargs: Any
    ) -> AgentResult:
        _ensure_crew_repo_on_path()
        settings = _configure_crew_llm()
        # CrewBase resolves config paths relative to the crew module's __file__,
        # so the instagram package must be importable as-is.
        from instagram.crew import InstagramCrew  # type: ignore[import-not-found]

        run_dir = _new_run_dir(settings.crew_output_dir, "instagram")
        # Inject runtime variables into the task descriptions via the same
        # {variable} placeholders the YAML configs declare. output_dir feeds
        # the tasks' output_file templates, so concurrent runs never
        # overwrite each other's files.
        runtime_vars = {
            "current_date": kwargs.get("current_date")
            or datetime.now(ZoneInfo(settings.user_timezone)).date().isoformat(),
            "instagram_description": context or task,
            "topic_of_the_week": task,
            "output_dir": run_dir.as_posix(),
        }
        result = await InstagramCrew().crew().kickoff_async(inputs=runtime_vars)

        artifacts = [
            {"name": name, "path": str(run_dir / name)}
            for name in INSTAGRAM_OUTPUT_FILES
            if (run_dir / name).is_file()
        ]
        return make_result(
            str(result),
            artifacts=artifacts,
            consulted_specialists=["cmo"],
            metadata={"crew": "instagram", "topic": task, "output_dir": str(run_dir)},
        )


def get_crewai_adapter(crew: str = "instagram") -> CrewAIAdapter:
    """Factory used by the skill-tool layer to build a CrewAI adapter."""
    return CrewAIAdapter(crew=crew)
