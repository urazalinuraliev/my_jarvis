"""Unit tests for the outbound_context storage layer (memory/episodic.py).

These rows link an outbound DM oe sent back to the conversation that triggered
it, so a recipient's reply can be hydrated with context. The store enforces:
bounded text, recency windows, most-recent-wins, and race-safe one-shot
consumption.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.memory.episodic import (
    _MAX_OUTBOUND_CONTEXT_CHARS,
    _get_conn,
    find_open_outbound_context,
    initialize_db,
    insert_outbound_context,
    mark_outbound_context_consumed,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "episodic.db"
    initialize_db(p)
    return p


def _backdate(db_path: Path, row_id: int, *, hours_ago: float) -> None:
    """Rewrite a row's created_at to simulate age (the insert API always uses now)."""
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            "UPDATE outbound_context SET created_at = ? WHERE id = ?", (ts, row_id)
        )


def test_insert_then_find_roundtrip(db_path: Path) -> None:
    row_id = insert_outbound_context(
        channel="discord_dm",
        channel_ref="alex-123",
        outbound_text="Heard you grabbed pizza instead of finishing the deck?",
        originating_session_id="discord:dm:principal-1",
        recipient_person_id=7,
        outbound_message_id="msg-999",
        db_path=db_path,
    )
    assert row_id > 0

    found = find_open_outbound_context(
        channel="discord_dm",
        channel_ref="alex-123",
        within=timedelta(hours=72),
        db_path=db_path,
    )
    assert found is not None
    assert found.id == row_id
    assert found.channel_ref == "alex-123"
    assert "pizza" in found.outbound_text
    assert found.originating_session_id == "discord:dm:principal-1"
    assert found.recipient_person_id == 7
    assert found.outbound_message_id == "msg-999"
    assert found.status == "open"


def test_insert_rejects_unknown_channel(db_path: Path) -> None:
    with pytest.raises(ValueError):
        insert_outbound_context(
            channel="carrier_pigeon",
            channel_ref="x",
            outbound_text="hi",
            db_path=db_path,
        )


def test_insert_accepts_email_channel(db_path: Path) -> None:
    """Email participates in the linkage too (recorded by the MCP gateway after
    a Gmail send), so `email` must be a valid channel."""
    row_id = insert_outbound_context(
        channel="email",
        channel_ref="alice@example.com",
        outbound_text="Can you confirm the Q3 budget?",
        originating_session_id="webchat:principal-1",
        db_path=db_path,
    )
    assert row_id > 0
    found = find_open_outbound_context(
        channel="email",
        channel_ref="alice@example.com",
        within=timedelta(hours=72),
        db_path=db_path,
    )
    assert found is not None
    assert found.channel == "email"
    assert found.originating_session_id == "webchat:principal-1"


def test_outbound_text_is_bounded(db_path: Path) -> None:
    huge = "x" * (_MAX_OUTBOUND_CONTEXT_CHARS + 500)
    insert_outbound_context(
        channel="telegram",
        channel_ref="555",
        outbound_text=huge,
        db_path=db_path,
    )
    found = find_open_outbound_context(
        channel="telegram", channel_ref="555", within=timedelta(hours=1), db_path=db_path
    )
    assert found is not None
    assert len(found.outbound_text) == _MAX_OUTBOUND_CONTEXT_CHARS


def test_find_excludes_rows_outside_window(db_path: Path) -> None:
    row_id = insert_outbound_context(
        channel="discord_dm",
        channel_ref="alex-123",
        outbound_text="old ping",
        db_path=db_path,
    )
    _backdate(db_path, row_id, hours_ago=100)
    found = find_open_outbound_context(
        channel="discord_dm",
        channel_ref="alex-123",
        within=timedelta(hours=72),
        db_path=db_path,
    )
    assert found is None


def test_find_returns_most_recent_open_row(db_path: Path) -> None:
    older = insert_outbound_context(
        channel="discord_dm", channel_ref="alex-123",
        outbound_text="first ping", db_path=db_path,
    )
    _backdate(db_path, older, hours_ago=2)
    newer = insert_outbound_context(
        channel="discord_dm", channel_ref="alex-123",
        outbound_text="second ping", db_path=db_path,
    )
    found = find_open_outbound_context(
        channel="discord_dm", channel_ref="alex-123",
        within=timedelta(hours=72), db_path=db_path,
    )
    assert found is not None
    assert found.id == newer
    assert found.outbound_text == "second ping"


def test_consumed_rows_are_excluded(db_path: Path) -> None:
    row_id = insert_outbound_context(
        channel="slack_dm", channel_ref="U1", outbound_text="ping", db_path=db_path
    )
    assert mark_outbound_context_consumed(row_id, db_path=db_path) is True
    found = find_open_outbound_context(
        channel="slack_dm", channel_ref="U1", within=timedelta(hours=72), db_path=db_path
    )
    assert found is None


def test_consume_is_one_shot(db_path: Path) -> None:
    row_id = insert_outbound_context(
        channel="discord_dm", channel_ref="alex-123",
        outbound_text="ping", db_path=db_path,
    )
    # First consume wins; second is a no-op (already consumed) — the guard that
    # makes concurrent replies race-safe (only the rowcount>0 caller injects).
    assert mark_outbound_context_consumed(row_id, db_path=db_path) is True
    assert mark_outbound_context_consumed(row_id, db_path=db_path) is False


def test_find_scopes_by_channel_and_ref(db_path: Path) -> None:
    insert_outbound_context(
        channel="discord_dm", channel_ref="alex-123",
        outbound_text="for alex", db_path=db_path,
    )
    # Different recipient on the same channel must not match.
    assert find_open_outbound_context(
        channel="discord_dm", channel_ref="someone-else",
        within=timedelta(hours=72), db_path=db_path,
    ) is None
    # Same ref but different channel must not match.
    assert find_open_outbound_context(
        channel="telegram", channel_ref="alex-123",
        within=timedelta(hours=72), db_path=db_path,
    ) is None


def test_find_returns_none_when_db_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"
    assert find_open_outbound_context(
        channel="discord_dm", channel_ref="x",
        within=timedelta(hours=72), db_path=missing,
    ) is None
