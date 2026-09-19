"""Honcho rejects session/peer IDs that don't match ``^[a-zA-Z0-9_-]+$``.

Adapter-generated session IDs like ``discord:thread:1508292084245725194``
or ``telegram:8519677317`` contain colons and get rejected with a 422
UnprocessableEntityError, so every sync_turn from those channels fails
before any data lands in Honcho. The wrapper sanitizes before sending.
"""
from __future__ import annotations

from openexecutive.memory.honcho_client import _safe_honcho_id


def test_discord_thread_session_id() -> None:
    assert (
        _safe_honcho_id("discord:thread:1508292084245725194")
        == "discord_thread_1508292084245725194"
    )


def test_telegram_chat_session_id() -> None:
    assert _safe_honcho_id("telegram:8519677317") == "telegram_8519677317"


def test_alphanumeric_passthrough() -> None:
    assert _safe_honcho_id("person-62") == "person-62"
    assert _safe_honcho_id("session_abc_123") == "session_abc_123"


def test_replaces_all_non_allowed_chars() -> None:
    assert _safe_honcho_id("a/b\\c d.e@f:g") == "a_b_c_d_e_f_g"


def test_empty_string_stays_empty() -> None:
    # Empty isn't a valid Honcho id, but the wrapper's caller-side fallback
    # (``session_id or f"person-{person_id}"``) handles that. The sanitizer
    # itself just shouldn't crash.
    assert _safe_honcho_id("") == ""
