"""Tests for the inbound resolver (3-tier WaitForHuman matching)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.memory import episodic
from openexecutive.workflows import persistence as wf_persistence
from openexecutive.workflows.inbound_resolver import resolve_inbound_message
from openexecutive.workflows.wait_for_human import WaitForHumanResolution


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setattr(episodic, "DB_PATH", db)
    monkeypatch.setattr(wf_persistence, "DB_PATH", db)
    episodic.initialize_db(db)
    wf_persistence.initialize_runs_db(db)
    yield


def _seed_awaiting_run(
    run_id: str,
    person_id: int,
    channel: str = "slack",
    outbound_message_id: str = "",
    *,
    db: Path,
) -> None:
    wf_persistence.create_run(run_id, "test_wf", "Test", {}, db_path=db)
    state = json.dumps({
        "on_timeout": "escalate",
        "channel": channel,
        "channel_ref": "U123",
        "outbound_message_id": outbound_message_id,
        "expected_reply_shape": "approve_reject",
        "question": "Please approve this vendor renegotiation.",
    })
    until = datetime.now(UTC) + timedelta(hours=48)
    wf_persistence.save_checkpoint(run_id, state, person_id, until, db_path=db)


def _run_resolver(**kwargs) -> WaitForHumanResolution | None:
    return asyncio.run(resolve_inbound_message(**kwargs))


# ---------------------------------------------------------------------------
# No candidates
# ---------------------------------------------------------------------------

def test_resolve_returns_none_when_no_candidates(tmp_path: Path) -> None:
    result = _run_resolver(
        channel="slack",
        channel_ref="U123",
        from_person_id=1,
        text="approved",
    )
    assert result is None


def test_resolve_returns_none_for_wrong_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=10, db=db)
    result = _run_resolver(
        channel="slack",
        channel_ref="U123",
        from_person_id=99,  # different person
        text="approved",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Tier 1: explicit in_reply_to
# ---------------------------------------------------------------------------

def test_resolve_tier1_explicit_message_id(tmp_path: Path) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=5, outbound_message_id="msg-abc", db=db)

    with patch("openexecutive.workflows.inbound_resolver.parse_decision", new=AsyncMock(return_value={"decision": "approve", "note": ""})):
        result = _run_resolver(
            channel="slack",
            channel_ref="U123",
            from_person_id=5,
            text="yes approved",
            in_reply_to="msg-abc",
        )
    assert result is not None
    assert result.run_id == "run-1"
    assert result.source_channel == "slack"
    assert result.person_id == 5


# ---------------------------------------------------------------------------
# Tier 2: single candidate
# ---------------------------------------------------------------------------

def test_resolve_by_single_candidate_match(tmp_path: Path) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=7, channel="slack", db=db)

    with patch("openexecutive.workflows.inbound_resolver.parse_decision", new=AsyncMock(return_value={"decision": "approve", "note": ""})):
        result = _run_resolver(
            channel="slack",
            channel_ref="U999",
            from_person_id=7,
            text="sounds good",
        )
    assert result is not None
    assert result.run_id == "run-1"
    assert result.person_id == 7


def test_resolve_single_candidate_parses_decision(tmp_path: Path) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=3, channel="slack", db=db)

    with patch("openexecutive.workflows.inbound_resolver.parse_decision", new=AsyncMock(return_value={"decision": "reject", "note": "too expensive"})):
        result = _run_resolver(
            channel="slack",
            channel_ref="U100",
            from_person_id=3,
            text="no reject",
        )
    assert result is not None
    assert result.parsed_decision == {"decision": "reject", "note": "too expensive"}


# ---------------------------------------------------------------------------
# Tier 3: multiple candidates — LLM disabled path
# ---------------------------------------------------------------------------

def test_resolve_returns_none_when_multiple_candidates_no_llm(tmp_path: Path) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=2, channel="slack", db=db)
    _seed_awaiting_run("run-2", person_id=2, channel="slack", db=db)

    with patch(
        "openexecutive.workflows.inbound_resolver._llm_disambiguate",
        return_value=(None, 0.5),  # low confidence
    ):
        result = _run_resolver(
            channel="slack",
            channel_ref="U200",
            from_person_id=2,
            text="ok",
        )
    assert result is None


def test_resolve_tier3_high_confidence_returns_match(tmp_path: Path) -> None:
    db = episodic.DB_PATH
    _seed_awaiting_run("run-1", person_id=2, channel="slack", db=db)
    _seed_awaiting_run("run-2", person_id=2, channel="slack", db=db)

    with patch(
        "openexecutive.workflows.inbound_resolver._llm_disambiguate",
        return_value=("run-2", 0.92),  # above threshold
    ), patch("openexecutive.workflows.inbound_resolver.parse_decision", new=AsyncMock(return_value={"decision": "approve", "note": ""})):
        result = _run_resolver(
            channel="slack",
            channel_ref="U200",
            from_person_id=2,
            text="yes this one",
        )
    assert result is not None
    assert result.run_id == "run-2"


# ---------------------------------------------------------------------------
# parse_decision (unit)
# ---------------------------------------------------------------------------

def _fake_provider(text: str | None = None, *, error: bool = False) -> MagicMock:
    """Provider stub whose async messages_create returns a content block
    carrying ``text`` (or raises, when error=True)."""
    provider = MagicMock()
    if error:
        provider.messages_create = AsyncMock(side_effect=RuntimeError("api down"))
    else:
        resp = type("Resp", (), {"content": [type("Block", (), {"text": text})()]})()
        provider.messages_create = AsyncMock(return_value=resp)
    return provider


def test_parse_decision_approve_reject() -> None:
    from openexecutive.workflows.wait_for_human import parse_decision
    provider = _fake_provider('{"decision": "approve", "note": "looks good"}')
    with patch("openexecutive.providers.get_provider", return_value=provider):
        result = asyncio.run(parse_decision("yes approved", "approve_reject"))
    assert result["decision"] == "approve"
    assert "note" in result


def test_parse_decision_free_text() -> None:
    from openexecutive.workflows.wait_for_human import parse_decision
    provider = _fake_provider('{"text": "The Q1 numbers are in the attachment"}')
    with patch("openexecutive.providers.get_provider", return_value=provider):
        result = asyncio.run(parse_decision("Q1 numbers attached", "free_text"))
    assert "text" in result


def test_parse_decision_falls_back_on_api_error() -> None:
    from openexecutive.workflows.wait_for_human import parse_decision
    provider = _fake_provider(error=True)
    with patch("openexecutive.providers.get_provider", return_value=provider):
        result = asyncio.run(parse_decision("yes", "approve_reject"))
    assert isinstance(result, dict)
    assert result["decision"] == "defer"
