from openexecutive.agents.base import BaseAgent
from openexecutive.config import get_settings


class TalentAgent(BaseAgent):
    """Talent & Executive Search specialist.

    Screens candidates against a search engagement's must-haves, maps the
    talent market for a mandate, and grounds advice in energy-sector hiring
    realities. Uses deep reasoning — candidate assessment is a judgment call
    that benefits from the extra thinking budget, same as the CFO/strategy
    specialists.
    """

    name = "talent"
    domain = "talent"
    use_deep_reasoning = True

    @property
    def model(self) -> str:  # type: ignore[override]
        return get_settings().deep_reasoning_model

    def get_system_prompt(self) -> str:
        from openexecutive.prompts.domain_prompts import TALENT_PROMPT

        return TALENT_PROMPT
