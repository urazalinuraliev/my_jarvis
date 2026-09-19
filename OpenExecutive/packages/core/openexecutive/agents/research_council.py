"""Council-configurable research model knob.

Surfaces a single virtual agent (``agent_id = "research"``) in the Agent
Council UI whose model + deep-reasoning fields control the
``executive_research`` 7-specialist fan-out (the research-mode turn driven
by ``monitoring.research.specialist_research``). This is intentionally ONE
knob for the whole fan-out, decoupled from each specialist's chat-time model
so a chat-quality bump on a specialist can't silently re-inflate research
cost.

Unlike ``utility_fast`` (model-only), this agent exposes BOTH a model and a
deep-reasoning toggle — both are cost levers for the research turn. Prompt
and role are placeholders; the UI hides those editors for this agent.

The resolution order for ``get_research_model()`` /
``get_research_use_deep_reasoning()`` mirrors the specialist override path:
DB override on ``research`` → ``settings.research_model`` / ``False`` default.
"""
from __future__ import annotations

from openexecutive.agents.base import BaseAgent

RESEARCH_AGENT_ID = "research"


class ResearchCouncilAgent(BaseAgent):
    name = RESEARCH_AGENT_ID
    domain = "utility"
    # Placeholder for BaseAgent's `model: str` slot — replaced on
    # instantiation with ``settings.research_model`` so the Council UI's
    # "default" label reflects the runtime RESEARCH_MODEL value.
    model = ""
    use_deep_reasoning = False

    def __init__(self) -> None:
        from openexecutive.config import get_settings

        self.model = get_settings().research_model

    def get_system_prompt(self) -> str:
        return ""


def get_research_model() -> str:
    """Return the model used for the executive_research specialist fan-out.

    Reads the Council override first, then falls back to
    ``settings.research_model`` so existing ``RESEARCH_MODEL`` env-var
    deployments keep working.
    """
    from openexecutive.agents.overrides import get_override
    from openexecutive.config import get_settings

    ov = get_override(RESEARCH_AGENT_ID)
    if ov is not None and ov.model is not None:
        return ov.model
    return get_settings().research_model


def get_research_use_deep_reasoning() -> bool:
    """Return whether the research turn should use deep reasoning.

    Reads the Council override first; defaults to ``False`` (the research
    turn is retrieve-from-web-search + summarize, which does not need
    adaptive thinking).
    """
    from openexecutive.agents.overrides import get_override

    ov = get_override(RESEARCH_AGENT_ID)
    if ov is not None and ov.use_deep_reasoning is not None:
        return ov.use_deep_reasoning
    return False
