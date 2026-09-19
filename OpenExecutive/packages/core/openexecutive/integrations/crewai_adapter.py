"""Run the CrewAI marketing crews of the sibling Smart-Marketing-Assistant-Crew-AI repo.

Two crews, both behind :class:`CrewAIAdapter` (the ``AgentAdapter`` contract):

* ``instagram`` — market research → content strategy → visuals → copywriting →
  final report (``src/instagram/crew.py``). Its Markdown deliverables land in a
  directory of their own under ``CREW_OUTPUT_DIR``, one per run.
* ``meeting_prep`` — participant research and industry analysis → meeting
  strategy → briefing (``src/agents.py`` and ``src/tasks.py``).

The crew repo is not a package dependency. It is located at run time — the
``CREWAI_REPO_PATH`` process env var, else the directory next to the
OpenExecutive checkout — and put on ``sys.path``. Where it or ``crewai`` is
missing (e.g. the Fly image), :func:`crew_unavailable_reason` says why, so
callers can hide or refuse the crews instead of failing mid-run. Nothing from
the crew repo or ``crewai`` is imported until a run starts.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from openexecutive.integrations.adapters import AgentAdapter, AgentResult, OutputFile

if TYPE_CHECKING:
    from openexecutive.config import Settings

SUPPORTED_CREWS: tuple[str, ...] = ("meeting_prep", "instagram")

# Files the Instagram crew writes (its tasks' ``{output_dir}/…`` output_file).
INSTAGRAM_OUTPUT_FILES: tuple[str, ...] = (
    "market_research.md",
    "visual-content.md",
    "final-content-strategy.md",
)

_CREW_REPO_NAME = "Smart-Marketing-Assistant-Crew-AI"


# --------------------------------------------------------------------------- #
# Locating the crew repo
# --------------------------------------------------------------------------- #


def _default_crew_repo() -> Path:
    # This file is .../OpenExecutive/packages/core/openexecutive/integrations/…;
    # the crew repo is expected next to the OpenExecutive checkout.
    here = Path(__file__).resolve()
    checkout_parent = here.parents[5] if len(here.parents) > 5 else here.parent
    return checkout_parent / _CREW_REPO_NAME


def crew_repo_path() -> Path:
    """Where the crew repo lives: ``CREWAI_REPO_PATH``, else next to this checkout."""
    configured = os.environ.get("CREWAI_REPO_PATH", "").strip()
    # A value starting with "#" is an inline .env comment that dotenv kept.
    if not configured or configured.startswith("#"):
        return _default_crew_repo()
    return Path(configured)


def crew_unavailable_reason() -> str | None:
    """Why the crews cannot run in this process, or ``None`` when they can.

    Cheap — a few file checks and a module lookup, no imports — so it can
    decide at import time whether to advertise the chat tool. The text names
    server paths: log it, never show it to chat users.
    """
    repo = crew_repo_path()
    if not (repo / "src").is_dir():
        return (
            f"The CrewAI crew repo was not found at {repo}. Clone "
            f"{_CREW_REPO_NAME} next to the OpenExecutive checkout or set "
            "CREWAI_REPO_PATH."
        )
    if not (repo / "src" / "crew_llm.py").is_file():
        # An unmodified upstream clone: its crews take no model from OE and
        # don't write into per-run directories.
        return (
            f"The CrewAI crew repo at {repo} is missing src/crew_llm.py, which "
            "this integration needs."
        )
    if find_spec("crewai") is None:
        return "The 'crewai' package is not installed (run `uv sync` in packages/core)."
    return None


def crew_integration_available() -> bool:
    return crew_unavailable_reason() is None


def _put_crew_repo_on_path() -> None:
    """Make the crew repo's top-level modules (agents, tasks, instagram, …) importable."""
    reason = crew_unavailable_reason()
    if reason is not None:
        raise RuntimeError(reason)
    src_dir = str(crew_repo_path() / "src")
    if src_dir not in sys.path:
        # Appended, not prepended: the crew's module names are generic and
        # must never shadow an installed package of the same name.
        sys.path.append(src_dir)


# --------------------------------------------------------------------------- #
# Choosing the model
# --------------------------------------------------------------------------- #


def resolve_crew_model(
    crewai_model: str | None, default_model: str, *, anthropic_direct: bool
) -> str | None:
    """The CrewAI model string for the crews' agents, or None when it must be set.

    ``CREWAI_MODEL`` wins. Otherwise a Claude ``DEFAULT_MODEL`` is reused on
    CrewAI's ``anthropic/`` provider, but only when OE itself sends it to
    Anthropic directly (*anthropic_direct*): with OpenRouter enabled, or the
    slug served locally, that would bypass the operator's routing and key.
    Any other ``DEFAULT_MODEL`` is an OpenRouter or local slug that CrewAI
    would misroute — it reads a ``vendor/`` prefix as "call that vendor" —
    so it is not guessed.
    """
    if crewai_model:
        return crewai_model
    if anthropic_direct and default_model.startswith("claude-"):
        return f"anthropic/{default_model}"
    return None


def _default_model_goes_to_anthropic(settings: Settings) -> bool:
    """Whether OE sends ``DEFAULT_MODEL`` straight to Anthropic.

    Mirrors the routing order of ``providers.registry.get_provider``: a
    ``LOCAL_MODELS`` entry stays local, and Claude goes through OpenRouter
    whenever that is enabled.
    """
    local_models = settings.local_models if settings.local_models_enabled else []
    return not settings.openrouter_enabled and settings.default_model not in local_models


def _provider_api_key(settings: Settings, model: str) -> str | None:
    """OE's key for the provider CrewAI will call for *model*, if OE holds one."""
    if model.startswith(("anthropic/", "claude-")):
        return settings.anthropic_api_key
    if model.startswith("openrouter/"):
        return settings.openrouter_api_key
    return None


def _configure_crew_llm() -> Settings:
    """Hand the crews their model and API key in-process; return the settings.

    They go through the crew repo's ``crew_llm.configure`` rather than
    environment variables, so the key never reaches child processes that
    inherit this process's environment.
    """
    import crew_llm  # type: ignore[import-not-found]

    from openexecutive.config import get_settings

    settings = get_settings()
    model = resolve_crew_model(
        settings.crewai_model,
        settings.default_model,
        anthropic_direct=_default_model_goes_to_anthropic(settings),
    )
    if model is None:
        raise RuntimeError(
            f"DEFAULT_MODEL={settings.default_model!r} is not served by Anthropic "
            "directly here (OpenRouter or local routing, or not a Claude model), so "
            "the CrewAI crews can't reuse it. Set CREWAI_MODEL to a CrewAI model "
            "string, e.g. anthropic/claude-sonnet-5 or openrouter/<model>."
        )
    crew_llm.configure(model=model, api_key=_provider_api_key(settings, model))
    # CrewAI sends anonymous usage telemetry by default; keep it off unless the
    # operator opts in, in line with the README's privacy promise.
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    return settings


# --------------------------------------------------------------------------- #
# Running the crews
# --------------------------------------------------------------------------- #


class CrewAIAdapter(AgentAdapter):
    """Runs one of the :data:`SUPPORTED_CREWS`.

    Both crews run through CrewAI's ``kickoff_async``, which executes the
    blocking pipeline in a worker thread, so a multi-minute run never stalls
    the event loop.
    """

    def __init__(self, crew: str = "instagram") -> None:
        if crew not in SUPPORTED_CREWS:
            raise ValueError(f"Unknown crew {crew!r}; expected one of {SUPPORTED_CREWS}")
        self.crew = crew

    async def run(self, *, task: str, context: str = "", **kwargs: Any) -> AgentResult:
        """Run the crew on *task*.

        instagram: *context* describes the account (defaults to *task*);
        ``current_date`` may be passed. meeting_prep: *context* is the meeting
        context (defaults to *task*); ``participants`` and ``objective`` may be
        passed.
        """
        _put_crew_repo_on_path()
        settings = _configure_crew_llm()
        if self.crew == "meeting_prep":
            return await _run_meeting_prep(
                meeting_context=context or task,
                participants=kwargs.get("participants") or "the meeting participants",
                objective=kwargs.get("objective") or "prepare for the meeting",
            )
        return await _run_instagram(
            topic=task,
            account_description=context or task,
            current_date=kwargs.get("current_date")
            or datetime.now(ZoneInfo(settings.user_timezone)).date().isoformat(),
            output_root=settings.crew_output_dir,
        )


def get_crewai_adapter(crew: str = "instagram") -> CrewAIAdapter:
    """Build the adapter for *crew* (the seam tests replace)."""
    return CrewAIAdapter(crew=crew)


async def _run_instagram(
    *, topic: str, account_description: str, current_date: str, output_root: Path
) -> AgentResult:
    # CrewBase resolves its YAML config relative to the crew module's file, so
    # the instagram package is imported from the crew repo as-is.
    from instagram.crew import InstagramCrew  # type: ignore[import-not-found]

    run_dir = _new_run_dir(output_root, "instagram")
    # These fill the {placeholders} in the crew's task YAML; output_dir feeds
    # its output_file templates.
    inputs = {
        "current_date": current_date,
        "instagram_description": account_description,
        "topic_of_the_week": topic,
        "output_dir": run_dir.as_posix(),
    }
    result = await InstagramCrew().crew().kickoff_async(inputs=inputs)

    files = [
        OutputFile(name=name, path=str(run_dir / name))
        for name in INSTAGRAM_OUTPUT_FILES
        if (run_dir / name).is_file()
    ]
    return AgentResult(
        text=str(result),
        files=files,
        consulted_specialists=["cmo"],
        metadata={"crew": "instagram", "topic": topic, "output_dir": str(run_dir)},
    )


async def _run_meeting_prep(
    *, meeting_context: str, participants: str, objective: str
) -> AgentResult:
    crew = _build_meeting_prep_crew(
        meeting_context=meeting_context, participants=participants, objective=objective
    )
    result = await crew.kickoff_async()
    return AgentResult(
        text=str(result),
        consulted_specialists=["cso", "cmo"],
        metadata={"crew": "meeting_prep", "participants": participants},
    )


def _build_meeting_prep_crew(*, meeting_context: str, participants: str, objective: str) -> Any:
    """Research and industry analysis run in parallel; the strategy builds on
    both, and the briefing on all three."""
    from agents import MeetingPrepAgents  # type: ignore[import-not-found]
    from crewai import Crew
    from tasks import MeetingPrepTask  # type: ignore[import-not-found]

    agent_factory = MeetingPrepAgents()
    task_factory = MeetingPrepTask()
    researcher = agent_factory.research_agent()
    analyst = agent_factory.industry_analysis_agent()
    strategist = agent_factory.meeting_strategy_agent()
    briefer = agent_factory.summary_and_briefing_agent()

    research = task_factory.research_task(researcher, participants, meeting_context)
    industry = task_factory.industry_analysis_task(analyst, participants, meeting_context)
    strategy = task_factory.meeting_strategy_task(strategist, meeting_context, objective)
    briefing = task_factory.summary_and_briefing_task(briefer, meeting_context, objective)
    research.context = []
    industry.context = []
    strategy.context = [research, industry]
    briefing.context = [research, industry, strategy]

    return Crew(
        agents=[researcher, analyst, strategist, briefer],
        tasks=[research, industry, strategy, briefing],
        verbose=True,
    )


def _new_run_dir(root: Path, crew: str) -> Path:
    """A fresh, uniquely named directory under *root* for one run's files."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"{stamp}-{crew}-{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True)
    return run_dir
