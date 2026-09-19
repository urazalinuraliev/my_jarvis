"""Fixture Generator — the LLM that authors company simulator fixtures.

Exposed through the Agent Council (like ``quality_judge`` / ``utility_fast``)
so its model can be switched in the UI and routed through OpenRouter, and its
system prompt edited per-deployment — but it lives OUTSIDE
``SPECIALIST_REGISTRY`` so the Executive cannot call it via the
``consult_specialist`` tool. ``openexecutive.fixtures.generator`` reads
``effective_model`` / ``effective_system_prompt`` at the start of every
generation, so Council edits take effect on the next request without a restart.
"""
from __future__ import annotations

from openexecutive.agents.base import BaseAgent
from openexecutive.config import get_settings

FIXTURE_GENERATOR_AGENT_ID = "fixture_generator"

# The author persona + hard rules. Kept here (not in fixtures/generator.py) so
# the Council prompt editor edits this text and there is no import cycle
# between the agent and the generator module.
FIXTURE_GENERATOR_SYSTEM = (
    "You are a fixture author for the Open Executive company simulator. Given a "
    "scenario description, you design a realistic, internally consistent fictional "
    "company and emit it via the emit_fixture tool. The company should feel like a "
    "real operating business: a coherent profile, a small leadership team, an org of "
    "departments with charters and goals, seeded history (decisions, initiatives, "
    "prior advice) and a few briefing alerts, plus 5-7 short knowledge docs.\n\n"
    "Hard rules:\n"
    "- Every department's head_person_name MUST exactly match a person's full_name.\n"
    "- Every alert's routed_to_person MUST exactly match a person's full_name.\n"
    "- Exactly one person has is_principal=true (the founder/CEO).\n"
    "- Department slugs are lowercase; people's department_slugs reference them.\n"
    "- NEVER invent email addresses or chat handles — omit all contact fields.\n"
    "- Numbers (ARR, burn, headcount) are numbers, not strings.\n"
    "- Make it specific and plausible: name real competitors/regulations where apt."
)


class FixtureGeneratorAgent(BaseAgent):
    name = FIXTURE_GENERATOR_AGENT_ID
    domain = "fixtures"
    use_deep_reasoning = False

    @property
    def model(self) -> str:  # type: ignore[override]
        # Read at access time so settings changes flow through. Same pattern
        # as QualityJudgeAgent / FinanceAgent.
        return get_settings().default_model

    def get_system_prompt(self) -> str:
        return FIXTURE_GENERATOR_SYSTEM
