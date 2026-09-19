"""Tests for the department + company-wide broadcast tools.

Covers:
- Missing / invalid arguments are rejected with a structured error
- Department without a channel configured returns the "no channel" error
- Company broadcast without a default channel returns the matching error
- Happy paths (Slack channel, Discord channel, Telegram chat) dispatch
  through the integration helper and return {"status": "sent", ...}

The actual SDK calls are stubbed — these tests verify the routing,
validation, and error-shape logic; they do NOT exercise the live Slack
or Discord HTTP paths.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openexecutive.departments import store as dept_store
from openexecutive.orchestrator import broadcast_tools


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "broadcast.db"
    monkeypatch.setattr(dept_store, "DB_PATH", db)
    dept_store.initialize_db(db)
    dept_store.seed_default_departments(db_path=db)
    return db


def _stub_post(
    monkeypatch: pytest.MonkeyPatch, target: str, response: dict[str, Any]
) -> dict[str, Any]:
    """Stub one of the integration-specific _post_* helpers, capture the args."""
    captured: dict[str, Any] = {}

    async def _stub(channel_id: str, text: str) -> dict[str, Any]:
        captured["channel_id"] = channel_id
        captured["text"] = text
        return response

    monkeypatch.setattr(broadcast_tools, target, _stub)
    return captured


# ---------------------------------------------------------------------------
# send_department_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_department_message_missing_text(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "slack",
            # text missing
        })
    )
    assert "error" in result
    assert "text" in result["error"].lower()


@pytest.mark.asyncio
async def test_department_message_empty_text(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "slack",
            "text": "   ",
        })
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_department_message_unknown_department(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "no-such-dept",
            "integration": "slack",
            "text": "hi",
        })
    )
    assert "error" in result
    assert "unknown department" in result["error"]


@pytest.mark.asyncio
async def test_department_message_unknown_integration(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "bogus",
            "text": "hi",
        })
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_department_message_no_channel_configured(isolated_db: Path) -> None:
    """Seeded departments have no channel configured by default — error must
    name the integration and point the user at the department detail page."""
    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "slack",
            "text": "hi",
        })
    )
    assert "error" in result
    assert "no slack channel configured" in result["error"]
    assert "/departments/finance" in result["error"]


@pytest.mark.asyncio
async def test_department_message_slack_happy_path(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dept_store.update_department(
        "finance", slack_channel_id="C12345", db_path=isolated_db
    )
    captured = _stub_post(monkeypatch, "_post_slack_channel", {"status": "sent", "channel": "C12345"})

    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "slack",
            "text": "Q3 burn trending high",
        })
    )

    assert result == {"status": "sent", "channel": "C12345"}
    assert captured["channel_id"] == "C12345"
    assert captured["text"] == "Q3 burn trending high"


@pytest.mark.asyncio
async def test_department_message_discord_happy_path(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dept_store.update_department(
        "finance", discord_channel_id="111222333444", db_path=isolated_db
    )
    captured = _stub_post(monkeypatch, "_post_discord_channel", {"status": "sent", "channel": "111222333444"})

    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "discord",
            "text": "burn alert",
        })
    )

    assert result["status"] == "sent"
    assert captured["channel_id"] == "111222333444"


@pytest.mark.asyncio
async def test_department_message_telegram_happy_path(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dept_store.update_department(
        "finance", telegram_chat_id="-100123456789", db_path=isolated_db
    )
    captured = _stub_post(monkeypatch, "_post_telegram_chat", {"status": "sent", "channel": "-100123456789"})

    result = json.loads(
        await broadcast_tools.handle_send_department_message({
            "department_slug": "finance",
            "integration": "telegram",
            "text": "test",
        })
    )

    assert result["status"] == "sent"
    assert captured["channel_id"] == "-100123456789"


# ---------------------------------------------------------------------------
# send_company_broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_company_broadcast_no_default_channel(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no default channel is configured for the integration, the tool
    must return an actionable error rather than silently no-op."""
    monkeypatch.delenv("SLACK_DEFAULT_CHANNEL_ID", raising=False)

    result = json.loads(
        await broadcast_tools.handle_send_company_broadcast({
            "integration": "slack",
            "text": "hi",
        })
    )
    assert "error" in result
    assert "company default slack channel not configured" in result["error"]


@pytest.mark.asyncio
async def test_company_broadcast_slack_happy_path(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLACK_DEFAULT_CHANNEL_ID", "C99GENERAL")
    captured = _stub_post(monkeypatch, "_post_slack_channel", {"status": "sent", "channel": "C99GENERAL"})

    result = json.loads(
        await broadcast_tools.handle_send_company_broadcast({
            "integration": "slack",
            "text": "Q3 plan shipped",
        })
    )
    assert result["status"] == "sent"
    assert captured["channel_id"] == "C99GENERAL"


@pytest.mark.asyncio
async def test_company_broadcast_text_validation(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_company_broadcast({
            "integration": "slack",
            "text": "",
        })
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_company_broadcast_unknown_integration(isolated_db: Path) -> None:
    result = json.loads(
        await broadcast_tools.handle_send_company_broadcast({
            "integration": "bogus",
            "text": "hi",
        })
    )
    assert "error" in result
    assert "unknown integration" in result["error"]
