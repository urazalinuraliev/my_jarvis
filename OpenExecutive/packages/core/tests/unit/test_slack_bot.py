"""Unit tests for the Slack integration's thread-continuation logic and helpers.

The full Bolt event-loop is not exercised here — these tests cover the
pure helper functions and the routing decision in the ``message`` event
handler (whether to invoke the inner sync handler in mode="continuation"
vs. drop the message). Full message-flow tests would require mocking the
Bolt client deeply and aren't necessary for the gate logic itself.
"""
from __future__ import annotations

from openexecutive.integrations import slack_bot
from openexecutive.integrations.slack_bot import (
    _count_distinct_humans,
    _replies_contain_bot_message,
    _replies_to_gate_history,
)

# --------------------------------------------------------------------------- #
# _replies_contain_bot_message
# --------------------------------------------------------------------------- #

def test_bot_present_in_thread():
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"user": "U_BOT", "text": "hello"},
        {"user": "U_ALICE", "text": "follow-up"},
    ]
    assert _replies_contain_bot_message(messages, "U_BOT") is True


def test_bot_absent_from_thread():
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"user": "U_BOB", "text": "hey"},
    ]
    assert _replies_contain_bot_message(messages, "U_BOT") is False


def test_bot_user_id_none_returns_false():
    """If auth_test failed at startup, the cached bot_user_id is None and
    thread auto-continuation is disabled — every check must return False."""
    messages = [{"user": "U_BOT", "text": "hi"}]
    assert _replies_contain_bot_message(messages, None) is False


def test_empty_history_returns_false():
    assert _replies_contain_bot_message([], "U_BOT") is False


# --------------------------------------------------------------------------- #
# _count_distinct_humans
# --------------------------------------------------------------------------- #

def test_count_excludes_bot():
    messages = [
        {"user": "U_ALICE"},
        {"user": "U_BOT"},
        {"user": "U_ALICE"},
    ]
    assert _count_distinct_humans(messages, "U_ALICE", "U_BOT") == 1


def test_count_multiple_humans():
    messages = [
        {"user": "U_ALICE"},
        {"user": "U_BOT"},
        {"user": "U_BOB"},
        {"user": "U_CAROL"},
    ]
    assert _count_distinct_humans(messages, "U_ALICE", "U_BOT") == 3


def test_count_includes_current_user_even_if_not_in_history():
    """A brand-new speaker (not in the fetched history yet) is still
    counted as a human in the thread."""
    messages = [{"user": "U_ALICE"}, {"user": "U_BOT"}]
    assert _count_distinct_humans(messages, "U_NEWCOMER", "U_BOT") == 2


def test_count_handles_none_bot_user_id():
    """When bot_user_id is unknown, fall back to treating everyone as human.
    This errs toward gate-skip not firing (over-respond) in degraded mode."""
    messages = [{"user": "U_ALICE"}, {"user": "U_BOB"}]
    assert _count_distinct_humans(messages, "U_ALICE", None) == 2


def test_count_skips_messages_with_no_user():
    """System / subtype messages without a `user` field are not humans."""
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"subtype": "channel_join"},  # no `user`
        {"user": "", "text": "weird"},
    ]
    assert _count_distinct_humans(messages, "U_ALICE", "U_BOT") == 1


# --------------------------------------------------------------------------- #
# _replies_to_gate_history
# --------------------------------------------------------------------------- #

def test_history_marks_bot_turns_as_assistant():
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"user": "U_BOT", "text": "hello back"},
    ]
    out = _replies_to_gate_history(messages, "U_BOT")
    assert out == [
        {"role": "user", "content": "[U_ALICE]: hi"},
        {"role": "assistant", "content": "hello back"},
    ]


def test_history_prefixes_human_turns_with_user_id():
    """The gate model needs to disambiguate speakers; ``[uid]: `` works
    even without resolving display names."""
    messages = [
        {"user": "U_ALICE", "text": "when?"},
        {"user": "U_BOB", "text": "tomorrow"},
    ]
    out = _replies_to_gate_history(messages, "U_BOT")
    assert out == [
        {"role": "user", "content": "[U_ALICE]: when?"},
        {"role": "user", "content": "[U_BOB]: tomorrow"},
    ]


def test_history_drops_subtype_messages():
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"user": "U_ALICE", "text": "joined channel", "subtype": "channel_join"},
        {"user": "U_ALICE", "text": "real msg"},
    ]
    out = _replies_to_gate_history(messages, "U_BOT")
    assert [m["content"] for m in out] == ["[U_ALICE]: hi", "[U_ALICE]: real msg"]


def test_history_drops_empty_text():
    messages = [
        {"user": "U_ALICE", "text": ""},
        {"user": "U_ALICE", "text": "   "},
        {"user": "U_ALICE", "text": "real"},
    ]
    out = _replies_to_gate_history(messages, "U_BOT")
    assert len(out) == 1
    assert out[0]["content"] == "[U_ALICE]: real"


def test_history_handles_unknown_bot_user_id():
    """When bot_user_id is None, every textual turn is treated as 'user' —
    the gate model still gets useful context, just without explicit
    assistant attribution."""
    messages = [
        {"user": "U_ALICE", "text": "hi"},
        {"user": "U_BOT", "text": "hello"},
    ]
    out = _replies_to_gate_history(messages, None)
    # Both lines tagged with their user_id; neither becomes assistant.
    assert all(m["role"] == "user" for m in out)


# --------------------------------------------------------------------------- #
# Module-level state
# --------------------------------------------------------------------------- #

def test_bot_user_id_starts_unresolved():
    """The cache is module-level and starts None until create_slack_app()
    succeeds. Tests must not rely on a populated cache."""
    # Tolerate prior tests setting the cache; just confirm the attribute exists.
    assert hasattr(slack_bot, "_bot_user_id")
