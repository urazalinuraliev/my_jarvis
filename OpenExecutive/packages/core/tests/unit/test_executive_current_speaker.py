"""The Executive must know who it is talking to so it never offers to "loop
in" / DM the human already in the room. _build_messages injects a
<current_speaker> hint into the user turn, resolved from person_id, and flags
the principal explicitly. See openexecutive.orchestrator.executive.
"""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")


def _speaker_text(content: list[dict]) -> str | None:
    """Return the <current_speaker> block text from a user-turn content list."""
    for part in content:
        text = part.get("text", "")
        if "<current_speaker>" in text:
            return text
    return None


def test_build_messages_flags_principal_speaker() -> None:
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.session import Session
    from openexecutive.people.models import Person

    principal = Person(id=1, full_name="Jordan One", role="Founder & CEO", is_principal=True)

    exec_ = Executive()
    with patch("openexecutive.people.store.get_person", return_value=principal):
        messages = exec_._build_messages(
            Session(session_id="t-speaker-1"),
            "what's on my plate today?",
            person_id=1,
        )

    block = _speaker_text(messages[-1]["content"])
    assert block is not None, "no <current_speaker> block injected for a resolved caller"
    assert "Jordan One" in block
    assert "principal" in block
    # The whole point: it must forbid looping the speaker in.
    assert "loop them in" in block


def test_build_messages_non_principal_speaker_still_guarded() -> None:
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.session import Session
    from openexecutive.people.models import Person

    person = Person(id=2, full_name="Jamie Lee", role="VP Sales", is_principal=False)

    exec_ = Executive()
    with patch("openexecutive.people.store.get_person", return_value=person):
        messages = exec_._build_messages(
            Session(session_id="t-speaker-2"),
            "status?",
            person_id=2,
        )

    block = _speaker_text(messages[-1]["content"])
    assert block is not None
    assert "Jamie Lee" in block
    assert "principal" not in block
    assert "loop them in" in block


def test_build_messages_no_speaker_block_when_person_unresolved() -> None:
    """CLI/curl path (person_id=None) and unknown ids leave the turn unchanged."""
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.session import Session

    exec_ = Executive()

    # person_id=None — no lookup at all.
    messages = exec_._build_messages(Session(session_id="t-speaker-3"), "hi", person_id=None)
    assert _speaker_text(messages[-1]["content"]) is None

    # person_id set but not found in roster — get_person returns None.
    with patch("openexecutive.people.store.get_person", return_value=None):
        messages = exec_._build_messages(Session(session_id="t-speaker-4"), "hi", person_id=999)
    assert _speaker_text(messages[-1]["content"]) is None


def test_speaker_block_swallows_lookup_errors() -> None:
    """A roster DB error must never break a chat turn — the block is dropped."""
    from openexecutive.orchestrator.executive import _build_current_speaker_block

    with patch("openexecutive.people.store.get_person", side_effect=RuntimeError("db down")):
        assert _build_current_speaker_block(7) is None
