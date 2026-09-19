"""Crisis comms playbook workflow — produces incident response messaging
templates: severity tiers, internal / customer / press / regulator
messaging, decision tree, and post-incident comms.

Uses the Board Comms, GC (General Counsel), and COO specialists.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.memory.company_profile import CompanyProfile
from openexecutive.onboarding.profile_builder import load_or_create_profile
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

_CC_EXAMPLE_INCIDENT = (
    "A confirmed security breach: an attacker accessed read-only credentials "
    "for our analytics replica via a compromised employee laptop. They "
    "had access for ~14 hours before our IDR rotated credentials. We "
    "believe they exported customer-level analytics events (no PII, but "
    "internal usage patterns) for ~3% of accounts. No production write "
    "access, no customer-account credentials touched."
)
_CC_EXAMPLE_AUDIENCES = (
    "Affected: ~50 enterprise + mid-market accounts in the 3% (named list "
    "available). Internal team (~40 people). Investor list (~12). "
    "Press: TechCrunch and Bloomberg have reached out — we have not "
    "responded yet. Regulatory: SOC 2 trust services criteria require "
    "disclosure within 72 hours."
)
_CC_EXAMPLE_KNOWN = (
    "Confirmed: timeline above, scope (3% of accounts), no PII, no write "
    "access. Unknown: whether the data was actually exfiltrated or just "
    "queryable (forensics ongoing), what the attacker's motive was, "
    "whether they retained any of the data."
)


class CrisisCommsInput(BaseModel):
    """Inputs for the Crisis Comms Playbook workflow."""

    incident_summary: str = Field(
        ...,
        description=(
            "What happened, factually. Avoid spin — the comms work depends "
            "on a clear-eyed view of the event."
        ),
        min_length=30,
        examples=[_CC_EXAMPLE_INCIDENT],
    )
    audiences: str = Field(
        ...,
        description=(
            "Who needs to hear something — customers (which ones), "
            "internal team, investors, press, regulators. Include any "
            "deadlines (e.g., SOC 2 72-hour clock)."
        ),
        min_length=20,
        examples=[_CC_EXAMPLE_AUDIENCES],
    )
    known_vs_unknown: str = Field(
        default="",
        description=(
            "Optional. What we know with confidence vs. what's still "
            "being investigated. This shapes how much we can say in "
            "first-wave comms."
        ),
        examples=[_CC_EXAMPLE_KNOWN],
    )


class CrisisCommsWorkflow(Workflow):
    name = "crisis_comms"
    title = "Crisis Comms Playbook"
    description = (
        "Drafts a crisis comms playbook for an incident — severity "
        "framing, decision tree, internal / customer / press / regulator "
        "messages, and post-incident comms. Uses the Board Comms, "
        "General Counsel, and COO specialists."
    )
    section = WorkflowSection.RISK
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return CrisisCommsInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "incident_summary": _CC_EXAMPLE_INCIDENT,
            "audiences": _CC_EXAMPLE_AUDIENCES,
            "known_vs_unknown": _CC_EXAMPLE_KNOWN,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and comms / legal RAG.",
            ),
            WorkflowStepDef(
                id="severity",
                title="Severity & decision tree",
                description="What tier this is and the resulting comms decisions.",
            ),
            WorkflowStepDef(
                id="legal_frame",
                title="Legal framing",
                description="What we must / must not say, and what we should never write down.",
            ),
            WorkflowStepDef(
                id="messages",
                title="Drafted messages",
                description="Internal / customer / press / regulator drafts.",
            ),
            WorkflowStepDef(
                id="ops",
                title="Operational sequencing",
                description="Who sends what when, and the rollback if facts change.",
            ),
            WorkflowStepDef(
                id="postmortem",
                title="Post-incident comms",
                description="What we say once the dust settles.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble playbook",
                description="Combine into one Markdown playbook.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, CrisisCommsInput)
        ctx = _CCCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="crisis communications incident response customer disclosure",
            specialist_name="board_comms",
            n_builtin=5,
            n_company=3,
            store=store,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="context",
            summary=(
                f"Loaded profile for {ctx.profile.name or 'company'} and "
                f"{_chunk_count(ctx.rag)} RAG chunks."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="severity", step_title="Severity & decision tree"
        )
        ctx.severity = await route_to_specialist(
            specialist_name="coo",
            query=_build_severity_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="severity", summary=_first_line(ctx.severity)
        )

        yield WorkflowEvent(
            type="step_start", step_id="legal_frame", step_title="Legal framing"
        )
        ctx.legal_frame = await route_to_specialist(
            specialist_name="gc",
            query=_build_legal_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="incident disclosure legal regulatory reporting obligations",
                specialist_name="gc",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="legal_frame", summary=_first_line(ctx.legal_frame)
        )

        yield WorkflowEvent(
            type="step_start", step_id="messages", step_title="Drafted messages"
        )
        ctx.messages = await route_to_specialist(
            specialist_name="board_comms",
            query=_build_messages_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="messages", summary=_first_line(ctx.messages)
        )

        yield WorkflowEvent(
            type="step_start", step_id="ops", step_title="Operational sequencing"
        )
        ctx.ops = await route_to_specialist(
            specialist_name="coo",
            query=_build_ops_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(type="step_done", step_id="ops", summary=_first_line(ctx.ops))

        yield WorkflowEvent(
            type="step_start", step_id="postmortem", step_title="Post-incident comms"
        )
        ctx.postmortem = await route_to_specialist(
            specialist_name="board_comms",
            query=_build_postmortem_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="postmortem", summary=_first_line(ctx.postmortem)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble playbook"
        )
        artifact = _assemble_doc(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 5 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _CCCtx:
    def __init__(self, inputs: CrisisCommsInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.severity: str = ""
        self.legal_frame: str = ""
        self.messages: str = ""
        self.ops: str = ""
        self.postmortem: str = ""


def _company_context_block(profile: CompanyProfile | None) -> str:
    if profile is None or profile.is_empty():
        return ""
    return profile.to_prompt_block()


def _chunk_count(rag_string: str) -> int:
    return rag_string.count("\n[") if rag_string else 0


def _first_line(text: str, max_len: int = 140) -> str:
    if not text:
        return "(empty)"
    line = text.strip().split("\n", 1)[0].lstrip("# ").strip()
    return line[: max_len - 1] + "…" if len(line) > max_len else line


def _build_severity_prompt(ctx: _CCCtx) -> str:
    unknown_block = (
        f"\n\nKnown vs. unknown:\n{ctx.inputs.known_vs_unknown}"
        if ctx.inputs.known_vs_unknown.strip()
        else ""
    )
    return (
        "Frame the **Severity & Decision Tree** for this incident.\n\n"
        f"Incident:\n{ctx.inputs.incident_summary}\n\n"
        f"Audiences:\n{ctx.inputs.audiences}{unknown_block}\n\n"
        "Output (Markdown):\n"
        "## Severity & Decision Tree\n\n"
        "### Severity tier\n"
        "Classify the incident on a 4-tier scale (SEV-1 customer-impacting "
        "data event / SEV-2 contained data event / SEV-3 service event / "
        "SEV-4 internal-only). Justify in 1 paragraph.\n\n"
        "### Decision tree\n"
        "Bullet list of decision points and the path the severity tier "
        "implies. Examples: customer notification within Xh / press "
        "statement / regulator filing / public status-page update. For "
        "each path, state who owns the decision.\n\n"
        "### Single source of truth\n"
        "1 paragraph: where the incident facts live (incident channel, "
        "live status doc) and who is allowed to update it. Drift between "
        "comms artifacts is how organizations get sued.\n\n"
        "Discipline: stick to facts as stated. If something is "
        "'unknown', it must show as 'unknown' in the messaging downstream."
    )


def _build_legal_prompt(ctx: _CCCtx) -> str:
    return (
        "From the **General Counsel** perspective, frame what we must / "
        "must not say.\n\n"
        f"Incident:\n{ctx.inputs.incident_summary}\n\n"
        f"Audiences:\n{ctx.inputs.audiences}\n\n"
        f"Known vs. unknown:\n{ctx.inputs.known_vs_unknown or '(not provided)'}\n\n"
        "Output (Markdown):\n"
        "## Legal Framing\n\n"
        "### Mandatory disclosures\n"
        "Bullet list of specific disclosures the incident may trigger "
        "(SOC 2, state breach laws, GDPR Article 33-34, contractual "
        "notification clauses in MSAs). For each: the time window and "
        "the threshold for application.\n\n"
        "### Language to avoid\n"
        "Bullet list of phrases that create liability or admit fault "
        "beyond what's known (e.g., 'breach' before it's confirmed, "
        "'unauthorized' without evidence of intent, 'all customer data' "
        "when only a subset is affected).\n\n"
        "### What to never write down\n"
        "1 paragraph: communications that should happen on phone or "
        "in-person (e.g., apportioning blame between vendors, "
        "speculative root-cause discussions before forensics complete).\n\n"
        "### Reps for external counsel\n"
        "Bullet list of questions our outside counsel should answer in "
        "the first 24 hours. Frame them concretely.\n\n"
        "Discipline: this is GC advice, not absolutism. Mark any item "
        "as '[jurisdiction-dependent — verify with outside counsel]' "
        "where regulations vary."
    )


def _build_messages_prompt(ctx: _CCCtx) -> str:
    return (
        "Draft the **Messages** for each audience. These are first-wave "
        "drafts — the team will sharpen with GC and the affected exec "
        "before sending.\n\n"
        f"Incident:\n{ctx.inputs.incident_summary}\n\n"
        f"Audiences:\n{ctx.inputs.audiences}\n\n"
        "Output (Markdown):\n"
        "## Drafted Messages\n\n"
        "### Internal team\n"
        "Slack-message-shaped draft (3-5 short paragraphs). Honest about "
        "the situation, names the incident commander, asks people to "
        "route inbound questions to a specific person.\n\n"
        "### Affected customers\n"
        "Email-shaped draft. Apology + specific facts (what happened, "
        "what data, what we've done) + what they should do + how to "
        "reach a human. Avoid speculative language.\n\n"
        "### Press statement\n"
        "3-4 sentence statement to be issued reactively. Factual, no "
        "speculation, names a contact for follow-up.\n\n"
        "### Regulator filing summary\n"
        "1 paragraph framing for the regulator notification. Use "
        "factual language; mark figures '[confirm with forensics]' "
        "where investigation continues.\n\n"
        "Discipline: every claim must be defensible against the "
        "incident summary. Do not invent facts to fill gaps. If a "
        "number is unknown, the message should say so."
    )


def _build_ops_prompt(ctx: _CCCtx) -> str:
    return (
        "Lay out the **Operational Sequencing** — who sends what, when, "
        "and the rollback if the facts change mid-disclosure.\n\n"
        f"Incident:\n{ctx.inputs.incident_summary}\n\n"
        f"Audiences:\n{ctx.inputs.audiences}\n\n"
        "Output (Markdown):\n"
        "## Operational Sequencing\n\n"
        "### Hour-by-hour\n"
        "Numbered list of hours T+0 through T+48, each with the action "
        "expected (internal notify / customer notify / press response / "
        "regulator filing / status-page updates). Owner each row.\n\n"
        "### Roles & escalation\n"
        "Bullet list: incident commander, comms lead, legal lead, exec "
        "spokesperson, customer-comms author. Backup for each.\n\n"
        "### If facts change\n"
        "1 paragraph: the rollback / amendment process if the "
        "investigation reveals the scope is larger (or smaller) than "
        "the first-wave messaging claimed. Naming this in advance "
        "prevents panic later.\n\n"
        "### Inbound channel\n"
        "1 paragraph: where inbound (customer / press / employee) "
        "questions go, who staffs it, how often they sync."
    )


def _build_postmortem_prompt(ctx: _CCCtx) -> str:
    return (
        "Draft the **Post-Incident Comms** — the messaging that comes "
        "after the dust settles. This is what shapes long-term trust.\n\n"
        f"Incident:\n{ctx.inputs.incident_summary}\n\n"
        "Output (Markdown):\n"
        "## Post-Incident Comms\n\n"
        "### Public postmortem\n"
        "Outline of the eventual public postmortem (if appropriate for "
        "the severity tier): timeline, root cause, remediation, what "
        "we'd do differently. Keep speculative-blame language out.\n\n"
        "### Customer follow-up\n"
        "1 paragraph: the 7-30 day follow-up to affected customers — "
        "what changed structurally, what they can verify themselves.\n\n"
        "### Internal lessons learned\n"
        "1 paragraph: framing for the internal all-hands debrief. No "
        "naming-and-shaming; focus on system-level changes.\n\n"
        "### Trust rebuilding\n"
        "1 paragraph: longer-term actions (3-6 month horizon) — "
        "audits, certifications, structural process changes — that "
        "demonstrate the response wasn't just talk.\n\n"
        "Discipline: a thoughtful, specific postmortem in 2 weeks beats "
        "a vague one in 24 hours. Note where we're committing to follow-up."
    )


def _assemble_doc(ctx: _CCCtx) -> str:
    parts = [
        "# Crisis Comms Playbook",
        "",
        "## Incident Summary",
        "",
        ctx.inputs.incident_summary.strip(),
        "",
        _ensure_heading(ctx.severity, "## Severity & Decision Tree"),
        "",
        _ensure_heading(ctx.legal_frame, "## Legal Framing"),
        "",
        _ensure_heading(ctx.messages, "## Drafted Messages"),
        "",
        _ensure_heading(ctx.ops, "## Operational Sequencing"),
        "",
        _ensure_heading(ctx.postmortem, "## Post-Incident Comms"),
        "",
        "---",
        "*Drafted by Open Executive. EVERY external message must be "
        "reviewed by outside counsel before it leaves the building. "
        "Treat this as a starting structure, not a script.*",
    ]
    return "\n".join(parts).strip() + "\n"


def _ensure_heading(text: str, expected_heading: str) -> str:
    stripped = text.strip()
    if not stripped:
        return f"{expected_heading}\n\n_(No content generated for this section.)_"
    first_line = stripped.split("\n", 1)[0]
    if first_line.startswith("##"):
        return stripped
    return f"{expected_heading}\n\n{stripped}"
