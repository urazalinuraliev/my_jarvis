"""Shared machinery for talent recruiting-automation workflows.

The Phase 3 workflows (candidate_outreach, interview_coordination,
reference_check) all follow the same draft-and-approve shape: resolve the
candidate + engagement + the principal who will act, then schedule reminders to
the *principal* (never to the candidate or a reference). This module centralizes
that context resolution, principal-channel routing, and reminder scheduling so
the workflows don't each reimplement (and drift on) the safety-critical "who is
the recipient" logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openexecutive.people.models import Person
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import Candidate, Engagement

# people.channel resolves to slack/discord/telegram/email; scheduled_actions
# rows use slack_dm/discord_dm/telegram/email. Mirror the bridge nudge_engine
# uses (kept local to avoid importing scheduler internals).
_PEOPLE_TO_SCHEDULED_CHANNEL = {
    "slack": "slack_dm",
    "discord": "discord_dm",
    "telegram": "telegram",
    "email": "email",
}
_CHANNEL_PRIORITY = ("email", "slack", "discord", "telegram")


def person_channel_raw(person: Person) -> tuple[str, str] | None:
    """Resolve a Person's (people_channel, channel_ref) in people vocabulary.

    Honors `preferred_channel`, else falls back through the priority order.
    Returns e.g. ``("slack", "U123")`` — the un-mapped channel name that
    ``WaitForHumanEvent.channel`` and the inbound resolver expect. Use
    :func:`principal_channel` when scheduling a reminder (scheduled_actions
    vocabulary, e.g. ``slack_dm``).
    """
    refs = {
        "email": person.email,
        "slack": person.slack_user_id,
        "discord": person.discord_user_id,
        "telegram": person.telegram_chat_id,
    }
    order: list[str] = []
    if person.preferred_channel != "any":
        order.append(person.preferred_channel)
    order.extend(c for c in _CHANNEL_PRIORITY if c not in order)
    for people_channel in order:
        ref = refs.get(people_channel)
        if ref and people_channel in _PEOPLE_TO_SCHEDULED_CHANNEL:
            return people_channel, ref
    return None


def principal_channel(person: Person) -> tuple[str, str] | None:
    """Resolve a Person's (scheduled_channel, channel_ref), or None.

    Honors `preferred_channel`, else falls back through the priority order, then
    maps the people-channel name to the scheduled_actions vocabulary.
    """
    raw = person_channel_raw(person)
    if raw is None:
        return None
    people_channel, ref = raw
    return _PEOPLE_TO_SCHEDULED_CHANNEL[people_channel], ref


def company_name() -> str:
    """This company's name from the profile (fallback ``"the company"``).

    In-house hiring: a search is run within this company, so workflow copy
    addresses the hiring org by the company's own name rather than an external
    client's.
    """
    from openexecutive.onboarding.profile_builder import load_or_create_profile

    profile = load_or_create_profile()
    return profile.name or "the company"


@dataclass
class ReminderContext:
    """Everything a talent workflow needs to schedule reminders to the principal."""

    candidate: Candidate
    engagement: Engagement
    company_name: str
    principal: Person
    channel: str
    channel_ref: str


def resolve_reminder_context(candidate_id: int) -> ReminderContext | str:
    """Resolve a candidate into a full reminder context, or return an error string.

    Returns a human-readable error message (str) when the candidate, its
    engagement, or a reachable principal can't be resolved — the workflow yields
    it as an `error` event and schedules nothing. This is the single place the
    recipient (always the principal, never the candidate) is determined.
    """
    candidate = talent_store.get_candidate(candidate_id)
    if candidate is None:
        return f"Candidate {candidate_id} not found."
    engagement = talent_store.get_engagement(candidate.engagement_id)
    if engagement is None:
        return f"Engagement {candidate.engagement_id} for this candidate not found."

    from openexecutive.people.store import find_principal_person

    principal = find_principal_person()
    if principal is None:
        return "No principal configured to receive reminders."
    routed = principal_channel(principal)
    if routed is None:
        return (
            f"Principal {principal.full_name} has no reachable channel "
            "(email/slack/discord/telegram) for reminders."
        )
    channel, channel_ref = routed
    return ReminderContext(
        candidate=candidate,
        engagement=engagement,
        company_name=company_name(),
        principal=principal,
        channel=channel,
        channel_ref=channel_ref,
    )


def artifact_header(
    ctx: ReminderContext,
    *,
    title: str,
    disclaimer: str,
    meta_lines: list[str] | None = None,
) -> list[str]:
    """Shared Markdown header for talent-workflow artifacts.

    Returns the title, role line, any caller-supplied meta lines, the
    "reminders to" line, and the draft-and-approve disclaimer — the block every
    talent workflow's artifact opens with.
    """
    lines = [
        f"# {title} — {ctx.candidate.full_name}",
        "",
        f"**Role:** {ctx.engagement.role_title} ({ctx.company_name})  ",
    ]
    lines.extend(meta_lines or [])
    lines += [
        f"**Reminders to:** {ctx.principal.full_name}",
        "",
        f"> {disclaimer}",
        "",
    ]
    return lines


def schedule_reminder(*, ctx: ReminderContext, run_at: datetime, intent_text: str) -> int:
    """Queue one reminder to the principal. Returns the scheduled_action id.

    The recipient is fixed to the principal's channel from `ctx` — candidate
    contact details never become a `channel_ref`.
    """
    from openexecutive.memory.episodic import insert_scheduled_action

    return insert_scheduled_action(
        run_at=run_at.isoformat(),
        channel=ctx.channel,
        channel_ref=ctx.channel_ref,
        intent_text=intent_text,
        assigned_to_person_id=ctx.principal.id,
        kind="ad_hoc",
    )
