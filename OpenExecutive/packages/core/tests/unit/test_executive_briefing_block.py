"""The <briefing> open-alert digest is injected into the user turn (and only
when non-empty), never into a cached system block — mirroring <past_decisions>.
"""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")


def _user_turn_texts(messages: list[dict]) -> list[str]:
    """Collect the text blocks of the final (user) turn."""
    user = messages[-1]
    assert user["role"] == "user"
    return [p["text"] for p in user["content"] if p.get("type") == "text"]


def test_briefing_block_present_when_provided() -> None:
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.session import Session

    exec_ = Executive()
    session = Session(session_id="t-brief-1")
    messages = exec_._build_messages(
        session,
        "hi",
        briefing_context="[7] (action) Gulf Coast Port Cyberattack — blocked",
    )
    texts = _user_turn_texts(messages)
    assert any(
        "<briefing>\n[7] (action) Gulf Coast Port Cyberattack — blocked\n</briefing>" in t
        for t in texts
    ), texts


def test_briefing_block_absent_when_empty() -> None:
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.session import Session

    exec_ = Executive()
    session = Session(session_id="t-brief-2")
    messages = exec_._build_messages(session, "hi", briefing_context="")
    texts = _user_turn_texts(messages)
    assert not any("<briefing>" in t for t in texts), texts
