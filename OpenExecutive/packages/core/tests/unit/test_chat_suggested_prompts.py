"""Tests for GET /chat/suggested-prompts.

Covers:
- Empty profile + no sessions returns the static fallback (prompts +
  subtitle) without invoking the LLM.
- A populated profile triggers the utility-fast LLM call; the parsed
  (prompts, subtitle) tuple becomes the response.
- LLM failures (timeout, malformed JSON, missing fields) fall back to
  the static set with the static subtitle.
- LLM failures are NOT cached.
- The cache key differentiates by profile.
- Cache hits skip the LLM on repeat.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import chat as chat_route
from openexecutive.memory.company_profile import (
    CompanyProfile,
    StrategicPriorities,
    TargetCustomer,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(chat_route.router)
    return app


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    chat_route._suggested_prompts_cache.clear()
    yield
    chat_route._suggested_prompts_cache.clear()


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    profile: CompanyProfile,
    sessions: list[dict[str, Any]],
) -> None:
    from openexecutive.memory import session_store
    from openexecutive.onboarding import profile_builder

    monkeypatch.setattr(profile_builder, "load_or_create_profile", lambda: profile)
    # list_sessions now takes a caller_person_id; the route passes whatever
    # `_resolve_caller_person_id` returns. Stub the resolver to a fixed id
    # so the route reaches list_sessions instead of short-circuiting on None.
    monkeypatch.setattr(session_store, "list_sessions", lambda _pid: sessions)
    monkeypatch.setattr(chat_route, "_resolve_caller_person_id", lambda _req: 1)


def test_empty_context_returns_fallback_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sources(monkeypatch, CompanyProfile(), [])

    called = {"n": 0}

    async def _boom(_: str) -> None:
        called["n"] += 1
        raise AssertionError("LLM should not be called when context is empty")

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _boom)

    with TestClient(_make_app()) as client:
        res = client.get("/chat/suggested-prompts")

    assert res.status_code == 200
    body = res.json()
    assert body["context_quality"] == "empty"
    assert body["prompts"] == chat_route._FALLBACK_PROMPTS
    assert body["subtitle"] == chat_route._FALLBACK_SUBTITLE
    assert called["n"] == 0


def test_populated_profile_uses_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = CompanyProfile(
        name="Acme",
        industry="B2B SaaS",
        stage="Series A",
        strategic_priorities=StrategicPriorities(
            current_year=["Ship onboarding v2"],
            north_star_metric="WAU",
        ),
        target_customer=TargetCustomer(profile="RevOps leads", pain_points=["manual reporting"]),
    )
    _patch_sources(monkeypatch, profile, [])

    expected_prompts = [
        "How are we tracking on onboarding v2?",
        "What's our WAU trend this quarter?",
        "Where are RevOps leads dropping off?",
        "Which manual reporting wins should we ship?",
    ]
    expected_subtitle = "Let's pressure-test the onboarding v2 plan before next week's standup."
    calls = {"n": 0}

    async def _fake_llm(_: str) -> tuple[list[str], str]:
        calls["n"] += 1
        return list(expected_prompts), expected_subtitle

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _fake_llm)

    with TestClient(_make_app()) as client:
        res = client.get("/chat/suggested-prompts")

    assert res.status_code == 200
    body = res.json()
    assert body["context_quality"] == "thin"  # profile yes, sessions no
    assert body["prompts"] == expected_prompts
    assert body["subtitle"] == expected_subtitle
    assert calls["n"] == 1


def test_llm_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = CompanyProfile(name="Acme", industry="B2B SaaS", stage="Series A")
    _patch_sources(monkeypatch, profile, [])

    async def _fail(_: str) -> None:
        return None  # simulate the route's failure path

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _fail)

    with TestClient(_make_app()) as client:
        res = client.get("/chat/suggested-prompts")

    assert res.status_code == 200
    body = res.json()
    assert body["prompts"] == chat_route._FALLBACK_PROMPTS
    assert body["subtitle"] == chat_route._FALLBACK_SUBTITLE
    assert body["context_quality"] == "empty"


def test_llm_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient LLM blip must not pin the static fallback for 10 minutes."""
    profile = CompanyProfile(name="Acme", industry="B2B SaaS", stage="Series A")
    _patch_sources(monkeypatch, profile, [])

    calls = {"n": 0}
    next_result: list[tuple[list[str], str] | None] = [
        None,
        (["A?", "B?", "C?", "D?"], "Recovered subtitle."),
    ]

    async def _fake_llm(_: str) -> tuple[list[str], str] | None:
        calls["n"] += 1
        return next_result.pop(0)

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _fake_llm)

    with TestClient(_make_app()) as client:
        r1 = client.get("/chat/suggested-prompts")
        r2 = client.get("/chat/suggested-prompts")

    assert r1.json()["prompts"] == chat_route._FALLBACK_PROMPTS
    assert r1.json()["subtitle"] == chat_route._FALLBACK_SUBTITLE
    assert r2.json()["prompts"] == ["A?", "B?", "C?", "D?"]
    assert r2.json()["subtitle"] == "Recovered subtitle."
    assert calls["n"] == 2, "failure must not be cached — second call should re-attempt"


def test_cache_differentiates_by_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different profiles must not collide in the cache."""
    from openexecutive.memory import session_store
    from openexecutive.onboarding import profile_builder

    profile_a = CompanyProfile(name="Acme", industry="SaaS", stage="Series A")
    profile_b = CompanyProfile(name="Globex", industry="Fintech", stage="Seed")

    state = {"profile": profile_a}
    monkeypatch.setattr(
        profile_builder, "load_or_create_profile", lambda: state["profile"]
    )
    monkeypatch.setattr(session_store, "list_sessions", lambda _pid: [])
    monkeypatch.setattr(chat_route, "_resolve_caller_person_id", lambda _req: 1)

    captured: list[tuple[list[str], str]] = [
        (["A1?", "A2?", "A3?", "A4?"], "Acme subtitle."),
        (["B1?", "B2?", "B3?", "B4?"], "Globex subtitle."),
    ]

    async def _fake_llm(_: str) -> tuple[list[str], str]:
        return captured.pop(0)

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _fake_llm)

    with TestClient(_make_app()) as client:
        r_a = client.get("/chat/suggested-prompts").json()
        state["profile"] = profile_b
        r_b = client.get("/chat/suggested-prompts").json()

    assert r_a["prompts"][0] == "A1?"
    assert r_a["subtitle"] == "Acme subtitle."
    assert r_b["prompts"][0] == "B1?", "different profile must miss the cache"
    assert r_b["subtitle"] == "Globex subtitle."


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeProvider:
    def __init__(self, text: str) -> None:
        self._text = text

    async def messages_create(self, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._text)


@pytest.mark.asyncio
async def test_llm_validator_handles_markdown_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model occasionally wraps its JSON in ```json fences — the fence
    stripping in _generate_prompts_via_llm must still parse + validate."""
    from openexecutive import providers
    from openexecutive.agents import utility_fast

    fenced = (
        "```json\n"
        '{"subtitle": "Tighten the Series A story before the partner meeting.", '
        '"prompts": ["What\'s our Q4 burn?", "How do we frame ARR growth?", '
        '"Where are we exposed on hiring?", "What should the board ask first?"]}\n'
        "```"
    )
    monkeypatch.setattr(utility_fast, "get_fast_model", lambda: "claude-haiku-test")
    monkeypatch.setattr(providers, "get_provider", lambda _model: _FakeProvider(fenced))

    result = await chat_route._generate_prompts_via_llm("ctx")
    assert result is not None
    prompts, subtitle = result
    assert len(prompts) == 4
    assert subtitle.startswith("Tighten the Series A")


@pytest.mark.asyncio
async def test_llm_validator_rejects_missing_subtitle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dict missing `subtitle` (or with empty/non-string subtitle) is
    rejected by the validator — the route's None branch then yields the
    static fallback."""
    from openexecutive import providers
    from openexecutive.agents import utility_fast

    no_subtitle = (
        '{"prompts": ["a?", "b?", "c?", "d?"]}'  # subtitle missing
    )
    monkeypatch.setattr(utility_fast, "get_fast_model", lambda: "claude-haiku-test")
    monkeypatch.setattr(
        providers, "get_provider", lambda _model: _FakeProvider(no_subtitle)
    )

    assert await chat_route._generate_prompts_via_llm("ctx") is None


def test_context_names_principal_reader() -> None:
    """The starter-card generator must know who is reading so it never
    suggests pulling the reader in on themselves (the 'pull in Jordan' bug)."""
    from openexecutive.people.models import Person

    profile = CompanyProfile(name="Acme", industry="SaaS", stage="Series A")
    rufus = Person(id=1, full_name="Jordan One", role="Founder & CEO", is_principal=True)

    quality, user_content = chat_route._build_prompts_context(profile, [], rufus)

    assert "CURRENT USER" in user_content
    assert "Jordan One" in user_content
    assert "principal" in user_content
    # Naming the reader must not change how grounded the context is judged.
    assert quality == "thin"


def test_context_names_non_principal_reader() -> None:
    from openexecutive.people.models import Person

    profile = CompanyProfile(name="Acme", industry="SaaS", stage="Series A")
    jamie = Person(id=2, full_name="Jamie Lee", role="VP Sales", is_principal=False)

    _quality, user_content = chat_route._build_prompts_context(profile, [], jamie)

    assert "CURRENT USER" in user_content
    assert "Jamie Lee" in user_content
    assert "principal" not in user_content


def test_context_omits_reader_line_when_caller_unknown() -> None:
    profile = CompanyProfile(name="Acme", industry="SaaS", stage="Series A")
    _quality, user_content = chat_route._build_prompts_context(profile, [], None)
    assert "CURRENT USER" not in user_content


def test_system_prompt_forbids_routing_to_reader() -> None:
    """The static rule that backs the behavior must stay in the system prompt."""
    assert "CURRENT USER" in chat_route._PROMPTS_SYSTEM
    assert "never the" in chat_route._PROMPTS_SYSTEM.lower()
    assert "reader" in chat_route._PROMPTS_SYSTEM.lower()


def test_cache_skips_repeat_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = CompanyProfile(name="Acme", industry="B2B SaaS", stage="Series A")
    sessions = [
        {"session_id": "s1", "title": "Pricing tiers debate"},
        {"session_id": "s2", "title": "Q3 hiring plan"},
    ]
    _patch_sources(monkeypatch, profile, sessions)

    calls = {"n": 0}

    async def _fake_llm(_: str) -> tuple[list[str], str]:
        calls["n"] += 1
        return ["A?", "B?", "C?", "D?"], "Cached subtitle."

    monkeypatch.setattr(chat_route, "_generate_prompts_via_llm", _fake_llm)

    with TestClient(_make_app()) as client:
        r1 = client.get("/chat/suggested-prompts")
        r2 = client.get("/chat/suggested-prompts")

    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["context_quality"] == "rich"  # profile + sessions both present
    assert r1.json()["subtitle"] == "Cached subtitle."
    assert calls["n"] == 1, "second call should be served from cache"
