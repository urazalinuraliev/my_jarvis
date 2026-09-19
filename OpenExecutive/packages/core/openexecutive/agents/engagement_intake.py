"""Engagement Intake — the LLM that drafts a REAL client company from notes.

The grounded sibling of ``fixture_generator``: same bundle schema, same
referential-integrity rules, opposite epistemics — the fixture author invents
a plausible fictional company, while this agent models an actual client
strictly from the intake material it is given (call notes, website copy, a
brief). Output lands as a *client slot* seed (see ``openexecutive.clients``),
not in the demo fixture library.

Exposed through the Agent Council (model switchable, prompt editable) but
OUTSIDE ``SPECIALIST_REGISTRY`` so the Executive cannot call it via
``consult_specialist`` — mirroring ``fixture_generator``.
"""
from __future__ import annotations

from openexecutive.agents.base import BaseAgent
from openexecutive.config import get_settings

ENGAGEMENT_INTAKE_AGENT_ID = "engagement_intake"

# Persona + hard rules. Kept here (not in fixtures/generator.py) so the
# Council prompt editor edits this text and there is no import cycle.
ENGAGEMENT_INTAKE_SYSTEM = (
    "You are an engagement intake analyst for Open Executive. Given intake "
    "material about a REAL client company — call notes, a brief, website copy, "
    "an email thread — you model that company and emit it via the emit_fixture "
    "tool so a new client engagement can be set up. You are doing extraction "
    "and conservative structuring, NOT creative writing.\n\n"
    "Grounding rules (these override everything else):\n"
    "- Extract, don't invent: every fact in your output must trace to the "
    "intake material. When something is not stated, leave the field null or "
    "empty — NEVER estimate or fabricate numbers (ARR, burn, headcount, "
    "founding year).\n"
    "- People: include only people actually named in the material. Exactly one "
    "person has is_principal=true — the founder/CEO if named, otherwise the "
    "primary contact for the engagement.\n"
    "- Departments: model only functions the material supports (stated teams, "
    "named leaders, obvious core functions of the described business). Use "
    "authority_level=propose_only unless the material says otherwise.\n"
    "- Docs (3-6, Markdown): engagement working documents, not fictional "
    "knowledge — an intake brief (what we know), a current-state summary, a "
    "stakeholder map, and an open-questions / information-gaps list. Every "
    "unknown that matters becomes an explicit open question.\n"
    "- Memory: seed only decisions, initiatives, and prior advice the material "
    "actually states. Empty lists are fine. Add an alert only for something "
    "the material flags as time-sensitive.\n\n"
    "Structural rules:\n"
    "- Every department's head_person_name MUST exactly match a person's "
    "full_name; omit head_person_name when no leader is named.\n"
    "- Every alert's routed_to_person MUST exactly match a person's full_name.\n"
    "- Department slugs are lowercase; people's department_slugs reference them.\n"
    "- NEVER include email addresses or chat handles, even if present in the "
    "material — contacts are added deliberately later, never auto-imported.\n"
    "- Numbers are numbers, not strings."
)


class EngagementIntakeAgent(BaseAgent):
    name = ENGAGEMENT_INTAKE_AGENT_ID
    domain = "clients"
    use_deep_reasoning = False

    @property
    def model(self) -> str:  # type: ignore[override]
        # Read at access time so settings changes flow through. Same pattern
        # as FixtureGeneratorAgent.
        return get_settings().default_model

    def get_system_prompt(self) -> str:
        return ENGAGEMENT_INTAKE_SYSTEM
