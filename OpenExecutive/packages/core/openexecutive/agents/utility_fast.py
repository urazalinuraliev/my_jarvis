"""Council-configurable utility/fast model knob.

Surfaces a single virtual agent (``agent_id = "utility_fast"``) in the
Agent Council UI whose model field controls all non-specialist Haiku
call sites:

- ``workflows.wait_for_human.parse_decision`` — parses human approval
  replies in Slack/email.
- ``workflows.inbound_resolver._llm_disambiguate`` — picks the right
  awaiting_human run when multiple are open for the same person.
- ``integrations.discord_bot`` — response gate + thread title generation.

The agent only exposes a model knob — prompt, role, and deep-reasoning
defaults are placeholders. The UI hides those editors for this agent.

The resolution order for ``get_fast_model()`` mirrors the specialist
override path: explicit kwarg (none here) → DB override on
``utility_fast`` → ``settings.routing_model`` default.
"""
from __future__ import annotations

from openexecutive.agents.base import BaseAgent

UTILITY_FAST_AGENT_ID = "utility_fast"


class UtilityFastAgent(BaseAgent):
    name = UTILITY_FAST_AGENT_ID
    domain = "utility"
    # Placeholder for BaseAgent's `model: str` slot — replaced on
    # instantiation with ``settings.routing_model`` so the Council UI's
    # "default" label reflects the runtime ROUTING_MODEL value.
    model = ""
    use_deep_reasoning = False

    def __init__(self) -> None:
        from openexecutive.config import get_settings

        self.model = get_settings().routing_model

    def get_system_prompt(self) -> str:
        return ""


def get_fast_model() -> str:
    """Return the model used for utility/fast tasks (routing gates,
    title generation, decision parsing).

    Reads the Council override first, then falls back to
    ``settings.routing_model`` so existing ``ROUTING_MODEL`` env-var
    deployments keep working.
    """
    from openexecutive.agents.overrides import get_override
    from openexecutive.config import get_settings

    ov = get_override(UTILITY_FAST_AGENT_ID)
    if ov is not None and ov.model is not None:
        return ov.model
    return get_settings().routing_model
