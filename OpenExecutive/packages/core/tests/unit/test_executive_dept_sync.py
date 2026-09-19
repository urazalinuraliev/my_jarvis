"""Unit tests for the Executive's per-turn department sync helper.

Covers ``_sync_consulted_departments_to_honcho``: the small helper that
fans out one ``sync_department_turn`` call per unique dept slug after
the person-side ``sync_turn`` has fired. The full streaming-loop
integration is exercised in test_executive_*; this file just locks down
the dedup, co-presence shape, and skip-on-no-dept behaviour of the
helper itself.
"""
from __future__ import annotations

from typing import Any

import pytest

from openexecutive.orchestrator import executive


@pytest.fixture
def captured_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Spy on sync_department_turn so tests can assert what was fired.

    The helper imports it lazily inside its body, so we patch on the
    honcho_client module (the import source) — patching on executive
    would miss the import."""
    calls: list[dict[str, Any]] = []

    def _spy(
        user_message: str,
        assistant_response: str,
        *,
        department_slug: str | None,
        session_id: str | None,
        originating_person_id: int | None = None,
        co_present_person_ids: list[int] | None = None,
        co_present_department_slugs: list[str] | None = None,
    ) -> None:
        calls.append(
            {
                "user_message": user_message,
                "assistant_response": assistant_response,
                "department_slug": department_slug,
                "session_id": session_id,
                "originating_person_id": originating_person_id,
                "co_present_person_ids": co_present_person_ids,
                "co_present_department_slugs": co_present_department_slugs,
            }
        )

    monkeypatch.setattr(
        "openexecutive.memory.honcho_client.sync_department_turn", _spy
    )
    return calls


def test_no_consulted_specialists_is_noop(
    captured_calls: list[dict[str, Any]],
) -> None:
    executive._sync_consulted_departments_to_honcho(
        consulted_specialists=[],
        user_message="u",
        response="a",
        person_id=42,
        session_id="s",
        co_present_person_ids=None,
    )
    assert captured_calls == []


def test_unique_dept_per_specialist_with_co_presence(
    captured_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two distinct dept-bound specialists → two syncs, each carrying
    the other's slug in co_present_department_slugs (the hybrid peer-
    graph cross-pollination the design called for)."""
    monkeypatch.setattr(
        "openexecutive.departments.registry.slug_for_specialist",
        lambda key: {"cfo": "finance", "cmo": "marketing"}.get(key),
    )
    executive._sync_consulted_departments_to_honcho(
        consulted_specialists=["cfo", "cmo"],
        user_message="cross-domain Q",
        response="cross-domain A",
        person_id=42,
        session_id="slack_C9_t1",
        co_present_person_ids=[55],
    )
    assert len(captured_calls) == 2
    finance_call = next(c for c in captured_calls if c["department_slug"] == "finance")
    marketing_call = next(c for c in captured_calls if c["department_slug"] == "marketing")
    # Each call must carry the OTHER dept slug as co-present.
    assert finance_call["co_present_department_slugs"] == ["marketing"]
    assert marketing_call["co_present_department_slugs"] == ["finance"]
    # Originator + other thread participants are forwarded uniformly.
    for c in captured_calls:
        assert c["originating_person_id"] == 42
        assert c["co_present_person_ids"] == [55]
        assert c["session_id"] == "slack_C9_t1"
        assert c["user_message"] == "cross-domain Q"
        assert c["assistant_response"] == "cross-domain A"


def test_duplicate_specialist_consults_dedup_to_one_dept_sync(
    captured_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Executive may consult the same specialist across multiple
    tool-use iterations in one turn. The dept peer should still get
    exactly one sync per unique dept slug per turn."""
    monkeypatch.setattr(
        "openexecutive.departments.registry.slug_for_specialist",
        lambda key: "finance" if key == "cfo" else None,
    )
    executive._sync_consulted_departments_to_honcho(
        consulted_specialists=["cfo", "cfo", "cfo"],
        user_message="u",
        response="a",
        person_id=1,
        session_id="s",
        co_present_person_ids=None,
    )
    assert len(captured_calls) == 1
    assert captured_calls[0]["department_slug"] == "finance"


def test_specialist_without_owning_dept_is_skipped(
    captured_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triage has no owning dept → no dept sync fires for it. The
    other consulted specialist still gets its sync."""
    monkeypatch.setattr(
        "openexecutive.departments.registry.slug_for_specialist",
        lambda key: "finance" if key == "cfo" else None,
    )
    executive._sync_consulted_departments_to_honcho(
        consulted_specialists=["triage", "cfo"],
        user_message="u",
        response="a",
        person_id=1,
        session_id="s",
        co_present_person_ids=None,
    )
    assert len(captured_calls) == 1
    assert captured_calls[0]["department_slug"] == "finance"
    # Co-present list is empty because no other dept ran this turn.
    assert captured_calls[0]["co_present_department_slugs"] == []
