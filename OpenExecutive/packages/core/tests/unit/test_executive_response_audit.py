"""Executive must emit a `chat_turn` audit row for its outbound response.

Before this fix, only the web `/api/chat` route emitted the response row —
so Discord / Slack / Telegram / Email / Google Chat turns went through
`.chat()` and never recorded the Executive's reply in the audit log. The
fix moves the emit into `stream_chat` and `stream_chat_with_committee`
themselves so every entry point captures the response uniformly.

These tests exercise the real methods with `_stream_agent_loop` stubbed,
so they catch regressions if the emit is removed or moved off the
success path.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from openexecutive.audit import AuditLogger, set_audit_logger
from openexecutive.memory.company_profile import CompanyProfile
from openexecutive.orchestrator.committee_reviewers import Critique
from openexecutive.orchestrator.executive import Executive
from openexecutive.orchestrator.session import Session


@pytest.fixture()
def audit(tmp_path: Path):
    """A temp-dir audit logger that the global `log_event` will route to."""
    instance = AuditLogger(tmp_path / "audit.db")
    set_audit_logger(instance)
    yield instance
    # Reset to None so other tests don't inherit our temp logger.
    set_audit_logger(None)


class _NoopAsyncStream:
    """Async context manager yielding zero text deltas."""

    async def __aenter__(self) -> _NoopAsyncStream:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    def __aiter__(self) -> _NoopAsyncStream:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration


def _drain(executive: Executive, session: Session, user_message: str) -> str:
    """Run stream_chat to completion and return the accumulated response."""

    async def _go() -> str:
        chunks: list[str] = []
        async for item in executive.stream_chat(
            user_message=user_message, session=session
        ):
            if isinstance(item, str):
                chunks.append(item)
        return "".join(chunks)

    return asyncio.run(_go())


def test_stream_chat_emits_response_chat_turn(audit: AuditLogger) -> None:
    """Non-committee path: one outbound chat_turn row per successful turn."""
    session = Session(session_id="sess-a", company_profile=CompanyProfile())

    async def _fake_loop(*_a: Any, **_kw: Any):  # type: ignore[no-untyped-def]
        yield "Hello "
        yield "from "
        yield "Executive."

    with patch.object(Executive, "_stream_agent_loop", new=_fake_loop):
        response = _drain(Executive(), session, "Hi there")

    assert response == "Hello from Executive."

    outbound = audit.query(event_type="chat_turn", actor="executive")
    assert len(outbound) == 1, "expected exactly one outbound chat_turn row"

    row = outbound[0]
    assert row.session_id == "sess-a"
    assert row.turn_id and row.turn_id.startswith("t-")
    assert row.summary.startswith("Executive: Hello from Executive.")
    assert row.details.get("direction") == "out"
    assert row.details.get("response_len") == len(response)
    assert row.details.get("committee") is False


def test_stream_chat_skips_audit_on_empty_response(audit: AuditLogger) -> None:
    """Empty response (tool-use only / max-iterations hit) must NOT emit a row.

    An empty 'Executive: ' audit row is noise without signal — the turn
    happened but the Executive produced no text. Other rows (memory
    snapshot, cache events) already capture what happened.
    """
    session = Session(session_id="sess-b", company_profile=CompanyProfile())

    async def _empty_loop(*_a: Any, **_kw: Any):  # type: ignore[no-untyped-def]
        # Yield only the THINKING sentinel which never accumulates into
        # full_response (see Executive._THINKING).
        if False:
            yield ""

    with patch.object(Executive, "_stream_agent_loop", new=_empty_loop):
        response = _drain(Executive(), session, "Hi")

    assert response == ""
    outbound = audit.query(event_type="chat_turn", actor="executive")
    assert outbound == [], "no chat_turn row should be emitted for empty response"


def test_stream_chat_with_committee_emits_response_chat_turn(
    audit: AuditLogger,
) -> None:
    """Committee path: emits its own chat_turn(committee=True) row.

    Different turn_id than the non-committee path (committee binds its
    own turn_id for the draft + reviews + revision span) and its full
    payload also carries the draft, for post-hoc debugging.
    """
    session = Session(session_id="sess-c", company_profile=CompanyProfile())

    async def _draft_loop(*_a: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        # Mimic the real draft loop populating its sinks.
        if kwargs.get("consulted_out") is not None:
            kwargs["consulted_out"].extend(["cfo"])
        if kwargs.get("specialist_outputs_out") is not None:
            kwargs["specialist_outputs_out"]["cfo"] = "ok"
        yield "draft "
        yield "text"

    async def _fake_review(*_a: Any, **_k: Any) -> list[Critique]:
        return [Critique("quality_judge", "low", "ok", "none")]

    # The revision pass iterates the provider's stream and appends
    # text_delta events to `final_response`. Mimic that shape so the
    # committee path produces a non-empty revised response.
    class _Delta:
        def __init__(self, text: str) -> None:
            self.type = "text_delta"
            self.text = text

    class _Event:
        def __init__(self, text: str) -> None:
            self.type = "content_block_delta"
            self.delta = _Delta(text)

    class _FakeStream:
        def __init__(self) -> None:
            self._events = iter([_Event("revised "), _Event("answer")])

        async def __aenter__(self) -> _FakeStream:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        def __aiter__(self) -> _FakeStream:
            return self

        async def __anext__(self) -> Any:
            try:
                return next(self._events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def get_final_message(self) -> None:
            return None

    class _FakeProvider:
        def messages_stream(self, **_kw: Any) -> _FakeStream:
            return _FakeStream()

    async def _go() -> str:
        chunks: list[str] = []
        async for item in Executive().stream_chat_with_committee(
            user_message="Hi", session=session
        ):
            if isinstance(item, str):
                chunks.append(item)
        return "".join(chunks)

    with (
        patch.object(Executive, "_stream_agent_loop", new=_draft_loop),
        patch(
            "openexecutive.orchestrator.committee.Committee.review",
            new=_fake_review,
        ),
        patch(
            "openexecutive.orchestrator.executive.get_provider",
            return_value=_FakeProvider(),
        ),
    ):
        response = asyncio.run(_go())

    # Caller drains the generator — committee yields the *draft* during
    # the draft phase plus the *revision* deltas during the revision
    # phase. final_response (and the audit row) capture the revision.
    assert "revised answer" in response
    outbound = audit.query(event_type="chat_turn", actor="executive")
    assert len(outbound) == 1, "committee path should emit one outbound chat_turn"
    row = outbound[0]
    assert row.details.get("committee") is True
    # The recorded response_len matches the revision text, not the
    # draft — committee_review=True turns require the audit row to
    # reflect what the user actually receives.
    assert row.details.get("response_len") == len("revised answer")
