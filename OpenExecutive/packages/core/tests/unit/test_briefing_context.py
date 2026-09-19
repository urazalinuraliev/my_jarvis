"""Unit tests for the chat-turn open-alert digest (`<briefing>` block source)."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.alerts.store import initialize_db, insert_alert, set_status
from openexecutive.briefing.context import (
    _BODY_SNIPPET_CHARS,
    format_open_alerts_for_prompt,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "alerts.db"
    initialize_db(db_path)
    return db_path


def test_empty_when_no_alerts(db: Path) -> None:
    assert format_open_alerts_for_prompt(db_path=db) == ""


def test_empty_when_db_missing(tmp_path: Path) -> None:
    # No DB file created → list_alerts short-circuits to []; formatter returns "".
    assert format_open_alerts_for_prompt(db_path=tmp_path / "nope.db") == ""


def test_renders_open_alert_fields(db: Path) -> None:
    aid = insert_alert(
        source="email",
        external_id="msg-1",
        severity="high",
        headline="Gulf Coast Port Cyberattack",
        body="Refined product movement is blocked at the terminal.",
        suggested_action="Have Legal review carrier contracts today.",
        topic_tags=["logistics", "security"],
        db_path=db,
    )
    out = format_open_alerts_for_prompt(db_path=db)

    assert f"[{aid}]" in out
    assert "Gulf Coast Port Cyberattack" in out
    assert "Refined product movement is blocked" in out
    assert "suggested: Have Legal review carrier contracts today." in out
    assert "tags: logistics, security" in out
    # High-severity, unrouted, non-external → action lane.
    assert "(action)" in out


def test_excludes_acked_and_dismissed(db: Path) -> None:
    keep = insert_alert(
        source="email",
        external_id="keep",
        severity="medium",
        headline="Still open",
        body="b",
        db_path=db,
    )
    acked = insert_alert(
        source="email",
        external_id="acked",
        severity="medium",
        headline="Already handled",
        body="b",
        db_path=db,
    )
    dismissed = insert_alert(
        source="email",
        external_id="dismissed",
        severity="medium",
        headline="Not interested",
        body="b",
        db_path=db,
    )
    assert acked is not None and dismissed is not None
    set_status(acked, "ack", db_path=db)
    set_status(dismissed, "dismissed", db_path=db)

    out = format_open_alerts_for_prompt(db_path=db)
    assert f"[{keep}]" in out
    assert "Already handled" not in out
    assert "Not interested" not in out


def test_body_is_truncated(db: Path) -> None:
    long_body = "x" * (_BODY_SNIPPET_CHARS + 200)
    insert_alert(
        source="email",
        external_id="long",
        severity="low",
        headline="Wordy alert",
        body=long_body,
        db_path=db,
    )
    out = format_open_alerts_for_prompt(db_path=db)
    assert "…" in out
    # The full body must not be reproduced verbatim.
    assert long_body not in out


def test_monitoring_signal_categorized(db: Path) -> None:
    # Unrouted, low-severity external signal → monitoring lane.
    insert_alert(
        source="stock",
        external_id="aapl",
        severity="low",
        headline="AAPL moved 1.2%",
        body="No obvious driver.",
        topic_tags=["external:stock-aapl"],
        db_path=db,
    )
    out = format_open_alerts_for_prompt(db_path=db)
    assert "(monitoring)" in out
