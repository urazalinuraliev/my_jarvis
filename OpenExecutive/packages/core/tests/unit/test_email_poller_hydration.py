"""The email poller hydrates an inbound reply with outbound context.

When the Executive emails someone during a web-chat (or any) session, a reply
arriving via the poller lands in a fresh `email:{thread}` session with no
originating context. `_run_executive` now calls the shared
`hydrate_user_message` helper (channel="email", keyed on the bare lowercased
sender address) so that reply carries the originating conversation's backstory —
the email analogue of the DM bots. No-op on a miss.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import openexecutive.integrations.email_poller as poller
import openexecutive.integrations.inbound_hydration as inbound_hydration
from openexecutive.memory import session_store
from openexecutive.memory.episodic import initialize_db, insert_outbound_context
from openexecutive.memory.session_store import create_session, save_message
from openexecutive.people import store as people_store


@pytest.fixture(autouse=True)
def isolated_people_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "people.db"
    monkeypatch.setattr(people_store, "DB_PATH", db_path)
    people_store.initialize_db()
    return db_path


@pytest.fixture(autouse=True)
def isolated_episodic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "episodic.db"
    initialize_db(db_path)
    monkeypatch.setattr("openexecutive.memory.episodic.DB_PATH", db_path)
    # hydration loads originating backstory via load_messages, which binds its
    # default db at import — inject the isolated path.
    monkeypatch.setattr(
        inbound_hydration,
        "load_messages",
        lambda session_id: session_store.load_messages(session_id, db_path),
    )
    return db_path


def _settings() -> Any:
    return SimpleNamespace(exec_email_address="exec@example.com", email_poll_interval_seconds=60)


def _capture_user_message(from_addr: str, raw_email_body: str) -> str:
    captured: dict[str, Any] = {}

    class _StubExecutive:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def chat(self, **kwargs: Any) -> Any:
            captured["user_message"] = kwargs.get("user_message", "")
            return None

    from openexecutive.memory import company_profile as _cp

    with (
        patch("openexecutive.orchestrator.executive.Executive", _StubExecutive),
        patch(
            "openexecutive.onboarding.profile_builder.load_or_create_profile",
            return_value=_cp.CompanyProfile(),
        ),
        patch("openexecutive.knowledge.retriever.retrieve", return_value=""),
        patch("openexecutive.memory.episodic.format_for_prompt", return_value=""),
        patch.object(poller, "get_settings", return_value=_settings()),
    ):
        asyncio.run(
            poller._run_executive(
                AsyncMock(),
                raw_email_body,
                message_id="m1",
                thread_id="t1",
                from_addr=from_addr,
                session_id=f"email:{from_addr}",
            )
        )
    return captured.get("user_message", "")


def _raw_email(from_addr: str) -> str:
    return f"Subject: Re: budget\nFrom: {from_addr}\n\nLooks good to me.\n"


def test_reply_is_hydrated_with_outbound_context(isolated_episodic_db: Path) -> None:
    people_store.upsert_person(full_name="Alice", email="alice@example.com")
    create_session("webchat:principal-1", "chat", "2026-06-01T00:00:00+00:00", db_path=isolated_episodic_db)
    save_message("webchat:principal-1", "user", "Ask Alice to confirm the Q3 budget.", db_path=isolated_episodic_db)
    insert_outbound_context(
        channel="email",
        channel_ref="alice@example.com",
        outbound_text="Hi Alice — can you confirm the Q3 budget numbers?",
        originating_session_id="webchat:principal-1",
        db_path=isolated_episodic_db,
    )

    user_message = _capture_user_message("alice@example.com", _raw_email("alice@example.com"))
    assert "<outbound_reply_context>" in user_message
    assert "confirm the Q3 budget" in user_message  # outbound text echoed
    assert "Looks good to me." in user_message  # original inbound preserved


def test_reply_keyed_on_lowercased_sender(isolated_episodic_db: Path) -> None:
    """A linkage stored bare-lowercased (as the gateway writes it) still hits
    when the inbound sender address is mixed-case. (The poller's parseaddr has
    already stripped any display name before _run_executive, so the address
    reaching here is bare — only case can differ.)"""
    people_store.upsert_person(full_name="Alice", email="alice@example.com")
    insert_outbound_context(
        channel="email",
        channel_ref="alice@example.com",
        outbound_text="ping about the budget",
        originating_session_id=None,
        db_path=isolated_episodic_db,
    )
    # email_poller resolves from_addr via parseaddr before reaching
    # _run_executive; pass the already-parsed bare address with odd case.
    user_message = _capture_user_message("Alice@Example.COM", _raw_email("Alice@Example.COM"))
    assert "<outbound_reply_context>" in user_message
    assert "ping about the budget" in user_message


def test_reply_without_linkage_passes_through(isolated_episodic_db: Path) -> None:
    people_store.upsert_person(full_name="Alice", email="alice@example.com")
    user_message = _capture_user_message("alice@example.com", _raw_email("alice@example.com"))
    assert "<outbound_reply_context>" not in user_message
    assert "Looks good to me." in user_message
