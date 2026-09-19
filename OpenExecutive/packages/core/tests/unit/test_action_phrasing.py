"""Tests for ``describe_executive_action`` — the concrete "If you approve:"
phrasing rendered on briefing proposal cards."""
from __future__ import annotations

from openexecutive.scheduler.action_phrasing import describe_executive_action


def test_department_channel_uses_department_name() -> None:
    out = describe_executive_action(
        kind="dept_cadence", channel="department_channel", department="sales"
    )
    assert out == "Send this check-in to the sales channel."


def test_department_slug_underscores_are_humanised() -> None:
    out = describe_executive_action(
        kind="dept_cadence", channel="department_channel", department="go_to_market"
    )
    assert out == "Send this check-in to the go to market channel."


def test_named_target_appends_dm_medium() -> None:
    out = describe_executive_action(
        kind="proactive_nudge", channel="slack_dm", target_name="Dana Lopez"
    )
    assert out == "Send this nudge to Dana Lopez via Slack DM."


def test_named_target_email_medium() -> None:
    out = describe_executive_action(
        kind="ad_hoc", channel="email", target_name="Dana Lopez"
    )
    assert out == "Send this follow-up to Dana Lopez by email."


def test_urgent_appends_right_away() -> None:
    out = describe_executive_action(
        kind="ad_hoc", channel="email", target_name="Dana Lopez", urgent=True
    )
    assert out == "Send this follow-up to Dana Lopez by email right away."


def test_company_broadcast_without_target() -> None:
    out = describe_executive_action(kind="ad_hoc", channel="company_broadcast")
    assert out == "Send this follow-up to the whole company."


def test_bare_channel_without_target() -> None:
    # No target name → fall back to the channel's "how" phrase.
    out = describe_executive_action(kind="proactive_nudge", channel="slack_dm")
    assert out == "Send this nudge via Slack DM."


def test_department_channel_without_department_degrades() -> None:
    out = describe_executive_action(kind="dept_cadence", channel="department_channel")
    assert out == "Send this check-in to the department channel."


def test_unknown_kind_and_channel_still_produce_a_sentence() -> None:
    # Graceful degradation: a newly-added taxonomy must never yield empty UI,
    # and the output is always a single punctuated sentence.
    out = describe_executive_action(kind="brand_new_kind", channel="__internal__")
    assert out == "Send this action."
    assert out.endswith(".")


def test_never_contains_circular_review_language() -> None:
    out = describe_executive_action(
        kind="dept_cadence", channel="department_channel", department="finance"
    )
    assert "review and approve" not in out.lower()
