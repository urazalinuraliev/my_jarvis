"""Unit tests for the draft_artifact chat/research tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openexecutive.alerts import store as alerts_store
from openexecutive.orchestrator.artifact_tools import handle_draft_artifact
from openexecutive.people import store as people_store


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A shared SQLite DB the alert + people stores both resolve to.

    The handler calls `insert_alert` / `find_principal_person` WITHOUT a
    db_path, so they read each module's module-level DB_PATH — patch both.
    Audit logging is fire-and-forget; stub it so tests don't touch a real
    episodic DB and so we can assert the audit row fired.
    """
    db_path = tmp_path / "episodic.db"
    alerts_store.initialize_db(db_path)
    people_store.initialize_db(db_path)
    monkeypatch.setattr(alerts_store, "DB_PATH", db_path)
    monkeypatch.setattr(people_store, "DB_PATH", db_path)
    return db_path


@pytest.fixture()
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def _record(event_type, summary, **kwargs):  # noqa: ANN001
        calls.append({"event_type": event_type, "summary": summary, **kwargs})

    monkeypatch.setattr("openexecutive.audit.log_event", _record)
    return calls


async def test_inserts_review_alert(db: Path, audit_calls: list[dict]) -> None:
    result = json.loads(await handle_draft_artifact({
        "title": "Competitor X just raised a Series B",
        "document": "## Summary\n\nThey raised $40M.\n\n- Implication one\n- Implication two",
        "why_interesting": "Changes our fundraising timeline assumptions.",
        "source_urls": ["https://example.com/news", "  "],
        "severity": "high",
    }))

    assert result["ok"] is True
    alert = alerts_store.get_alert(result["alert_id"], db_path=db)
    assert alert is not None
    assert alert.source == "artifact"
    assert alert.topic_tags == ["artifact"]
    assert alert.headline == "Competitor X just raised a Series B"
    assert "They raised $40M." in alert.body
    assert "### Sources" in alert.body
    assert "https://example.com/news" in alert.body
    assert alert.suggested_action == "Changes our fundraising timeline assumptions."
    assert alert.severity == "high"
    assert alert.status == "unread"
    # The audit row fired with the draft_artifact tool tag.
    assert any(c["event_type"] == "tool_invocation"
               and c["details"]["tool"] == "draft_artifact"
               and c["details"]["ok"] is True
               for c in audit_calls)


async def test_routes_to_principal(db: Path, audit_calls: list[dict]) -> None:
    pid = people_store.upsert_person(
        full_name="Jordan", role="CEO", is_principal=True, db_path=db,
    )
    result = json.loads(await handle_draft_artifact({
        "title": "Memo", "document": "Body", "why_interesting": "Worth a read",
    }))
    alert = alerts_store.get_alert(result["alert_id"], db_path=db)
    assert alert is not None
    assert alert.routed_to_person_id == pid


async def test_no_principal_tolerated(db: Path, audit_calls: list[dict]) -> None:
    result = json.loads(await handle_draft_artifact({
        "title": "Memo", "document": "Body", "why_interesting": "Worth a read",
    }))
    assert result["ok"] is True
    alert = alerts_store.get_alert(result["alert_id"], db_path=db)
    assert alert is not None
    assert alert.routed_to_person_id is None


async def test_invalid_severity_defaults_to_medium(db: Path, audit_calls: list[dict]) -> None:
    result = json.loads(await handle_draft_artifact({
        "title": "Memo", "document": "Body", "why_interesting": "x", "severity": "bogus",
    }))
    alert = alerts_store.get_alert(result["alert_id"], db_path=db)
    assert alert is not None
    assert alert.severity == "medium"


@pytest.mark.parametrize("payload", [
    {"title": "Memo", "document": "  ", "why_interesting": "x"},
    {"title": "  ", "document": "Body", "why_interesting": "x"},
    {"title": "Memo", "document": "Body", "why_interesting": "  "},
])
async def test_rejects_missing_required_fields(
    db: Path, audit_calls: list[dict], payload: dict,
) -> None:
    result = json.loads(await handle_draft_artifact(payload))
    assert "error" in result
    assert alerts_store.list_alerts(db_path=db) == []


async def test_does_not_invoke_triage_pipeline(
    db: Path, audit_calls: list[dict], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifacts must land verbatim — never through the triage rewriter."""
    triage_calls: list[object] = []
    monkeypatch.setattr(
        "openexecutive.alerts.pipeline.schedule_evaluation",
        lambda event: triage_calls.append(event),
    )
    await handle_draft_artifact({
        "title": "Memo", "document": "Body", "why_interesting": "x",
    })
    assert triage_calls == []
