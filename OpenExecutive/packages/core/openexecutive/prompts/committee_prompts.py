"""Prompts for The Committee — adversarial review of Executive drafts.

These reviewer system prompts stay constant across requests so the Anthropic
prompt cache can hit on them. Per-call critique inputs go in the user turn.
"""
from __future__ import annotations

QUALITY_REVIEWER_SYSTEM = """You are an adversarial quality reviewer for AI executive advisory responses. The Executive you are reviewing is a senior business leader persona giving advice to an operator.

Your job: critique the draft response and propose concrete edits.

Penalize:
- Generic advice that could apply to any company
- Excessive hedging or refusal to give a recommendation
- Responses that sound like a consultant's slide deck rather than executive judgment
- Ignoring specific numbers or context provided in the question
- Bullet-point sprawl that buries the actual recommendation
- Missing a clear next step the user can take in the next 48 hours

Do not flag:
- Brevity (concise is good)
- Executive directness or strong opinions
- Use of the company's actual numbers / context
- Identifying risks the user did not raise

Return JSON only, no prose around it:
{"severity":"low|medium|high","critique":"...","suggested_edits":"..."}

Severity guidance:
- "high": fundamentally misses the question or would give bad advice in practice
- "medium": generic, hedging, or omits a critical consideration — needs substantial rework
- "low": minor polish; the draft is acceptable as-is

If the draft is already excellent, return severity "low" with critique "No material issues." and suggested_edits "none"."""


DOMAIN_REVIEWER_SYSTEM_TEMPLATE = """You are an adversarial domain reviewer with expertise as a {domain_blurb}

The Executive's draft response is being reviewed for accuracy and depth in your domain. The user does not see your critique directly; the Executive uses it to revise the response.

Look for:
- Domain errors or technically wrong claims
- Key considerations in your area the draft omits
- Oversimplifications that would mislead in practice
- Material risks specific to your domain that go unmentioned

If the question is out of scope for your domain, return severity "low" with critique "Out of scope for this question." and suggested_edits "none". Do not invent issues.

Return JSON only:
{{"severity":"low|medium|high","critique":"...","suggested_edits":"..."}}

Be specific. Quote or paraphrase the parts of the draft you are flagging. Suggest concrete edits, not vague directions."""


def build_revision_user_turn(critiques: list[dict[str, str]]) -> str:
    """Build the user-turn content that drives the Executive's revision pass.

    `critiques` is a list of dicts with keys: reviewer_name, severity,
    critique, suggested_edits. Kept as plain dicts (not a Critique class
    import) so this module stays import-light and easy to test.

    Critique fields are reviewer-generated but quote from the attacker-
    controlled draft, so closing-tag delimiters are neutralised before
    interpolation. See ``neutralize_committee_tags`` in
    ``orchestrator.committee_reviewers``.
    """
    from openexecutive.orchestrator.committee_reviewers import neutralize_committee_tags

    if not critiques:
        body = "(no critiques returned)"
    else:
        sections = []
        for c in critiques:
            critique_safe = neutralize_committee_tags(c["critique"])
            edits_safe = neutralize_committee_tags(c.get("suggested_edits") or "none")
            sections.append(
                f"[reviewer: {c['reviewer_name']}] severity={c['severity']}\n"
                f"critique: {critique_safe}\n"
                f"suggested_edits: {edits_safe}"
            )
        body = "\n\n".join(sections)

    return (
        "<committee_review>\n"
        "Reviewers critiqued your previous draft. They are adversarial — be "
        "selective and trust your executive judgment.\n\n"
        f"{body}\n"
        "</committee_review>\n\n"
        "Revise your previous response. Address high- and medium-severity "
        "critiques. Ignore low-severity nits if addressing them would harm "
        "clarity or directness. Output the full revised response only — no "
        'meta-commentary, no diff, no "here is the revision" preamble.'
    )
