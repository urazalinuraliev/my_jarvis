"""Quality Judge — Committee reviewer exposed as an overridable agent.

Lives outside ``SPECIALIST_REGISTRY`` so the Executive cannot call it via
the ``consult_specialist`` tool, but it *is* surfaced through the Agent
Council so its prompt and model can be edited per-deployment. The
Committee reads ``effective_system_prompt`` / ``effective_model`` at the
start of every review, so Council edits take effect on the next turn
without a process restart.
"""
from __future__ import annotations

from openexecutive.agents.base import BaseAgent
from openexecutive.config import get_settings


class QualityJudgeAgent(BaseAgent):
    name = "quality_judge"
    domain = "review"
    use_deep_reasoning = False

    @property
    def model(self) -> str:  # type: ignore[override]
        # Read at access time so settings changes flow through. Same
        # pattern used by FinanceAgent / TriageAgent.
        return get_settings().default_model

    def get_system_prompt(self) -> str:
        from openexecutive.prompts.committee_prompts import QUALITY_REVIEWER_SYSTEM

        return QUALITY_REVIEWER_SYSTEM
