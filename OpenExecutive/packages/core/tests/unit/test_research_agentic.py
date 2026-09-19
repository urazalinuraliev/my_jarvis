"""Unit tests for the agentic research scrape loop.

The provider's ``messages_create`` is mocked to return a scripted
multi-turn sequence, and ``xcrawl_client.scrape`` is mocked — no network,
no real model. Covers: scrape→emit happy path (markdown fed back),
mandatory read-before-cite (a 0-scrape emit is rejected and forced to read,
except when scraping is impossible or the iteration cap is hit), scrape
budget cap, no-progress stop, provider failure, iteration cap, the
scrape_tool handler, and the enabled/disabled dispatch branch.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openexecutive.monitoring.research import agentic, scrape_tool
from openexecutive.monitoring.research import specialist_research as sr

_FINDING = {
    "title": "GM cut Equinox EV price",
    "summary": "GM cut the Equinox EV price by $3,000 on 2026-05-20.",
    "severity_hint": "medium",
    "suggested_audience": "principal",
    "confidence": "high",
    "relevant_urls": ["https://gmauthority.com/blog/2026/05/cut"],
}


# ---- block / message factories (mimic the provider Message shape) ---------

def _text(t: str = "thinking") -> Any:
    return SimpleNamespace(type="text", text=t)


def _scrape(url: str, _id: str = "s1") -> Any:
    return SimpleNamespace(
        type="tool_use", name="scrape_url", id=_id, input={"url": url},
    )


def _emit(findings: list[dict], _id: str = "e1") -> Any:
    return SimpleNamespace(
        type="tool_use", name="emit_research_findings", id=_id,
        input={"findings": findings},
    )


def _msg(blocks: list[Any]) -> Any:
    return SimpleNamespace(content=blocks, stop_reason="tool_use")


class _FakeAgent:
    def effective_system_prompt(self) -> str:
        return "PERSONA"


class _FakeProvider:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def messages_create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        if idx < len(self.responses):
            r = self.responses[idx]
            if isinstance(r, Exception):
                raise r
            return r
        return _msg([_text("done")])  # ran out → no emit → loop stops


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[Any],
    scrape: Any = "ARTICLE FULL TEXT",
) -> _FakeProvider:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    monkeypatch.setenv("XCRAWL_API_KEY", "dummy")
    monkeypatch.setenv("RESEARCH_AGENTIC_SCRAPE_ENABLED", "true")
    provider = _FakeProvider(responses)
    monkeypatch.setattr(agentic, "get_provider", lambda model: provider)

    calls = {"n": 0}

    async def fake_scrape(url: str) -> str | None:
        calls["n"] += 1
        return scrape

    monkeypatch.setattr(scrape_tool.xcrawl_client, "scrape", fake_scrape)
    provider.scrape_calls = calls  # type: ignore[attr-defined]
    return provider


# --------------------------------------------------------------------- #
# Loop behavior
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_scrapes_then_emits_and_feeds_markdown_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _install(monkeypatch, responses=[
        _msg([_text("let me read this"), _scrape("https://gmauthority.com/x")]),
        _msg([_emit([_FINDING])]),
    ])
    out = await agentic.run_specialist_agentic("cso", _FakeAgent(), "CTX")

    assert len(out) == 1 and out[0].title == _FINDING["title"]
    assert provider.scrape_calls["n"] == 1  # the page was actually scraped
    # The scraped markdown was fed back as a tool_result on the 2nd call.
    second_call_messages = provider.calls[1]["messages"]
    tool_results = second_call_messages[-1]["content"]
    assert tool_results[0]["type"] == "tool_result"
    assert tool_results[0]["content"] == "ARTICLE FULL TEXT"


@pytest.mark.asyncio
async def test_emit_accepted_on_first_turn_when_scrape_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # max_scrapes == 0 → scraping is impossible, so a turn-1 emit can't be
    # forced to read first; accept it rather than trap the model.
    monkeypatch.setenv("RESEARCH_SCRAPE_MAX_PER_SPECIALIST", "0")
    provider = _install(monkeypatch, responses=[_msg([_emit([_FINDING])])])
    out = await agentic.run_specialist_agentic("cfo", _FakeAgent(), "CTX")
    assert len(out) == 1
    assert provider.scrape_calls["n"] == 0
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_emit_with_zero_scrapes_is_rejected_then_forced_to_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The core mandatory-scrape contract: the model tries to emit on turn 1
    # without having read anything; the loop rejects that emit, the model is
    # forced to scrape, and only the post-scrape emit is accepted.
    provider = _install(monkeypatch, responses=[
        _msg([_emit([_FINDING], "e_early")]),         # turn 1: premature emit
        _msg([_scrape("https://gmauthority.com/x")]),  # turn 2: forced read
        _msg([_emit([_FINDING], "e_final")]),          # turn 3: grounded emit
    ])
    out = await agentic.run_specialist_agentic("cso", _FakeAgent(), "CTX")

    assert len(out) == 1 and out[0].title == _FINDING["title"]
    assert provider.scrape_calls["n"] == 1          # it was forced to read
    assert len(provider.calls) == 3                 # rejected, scraped, emitted
    # The rejection tool_result must be paired to the premature emit's id.
    # (`messages` is one list mutated in place, so scan the final history for
    # the tool_result rather than index a specific call.)
    final_messages = provider.calls[-1]["messages"]
    results = [
        block
        for m in final_messages if m["role"] == "user"
        and isinstance(m["content"], list)
        for block in m["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    rejection = next(r for r in results if r["tool_use_id"] == "e_early")
    assert "scrape_url" in rejection["content"]


@pytest.mark.asyncio
async def test_emit_accepted_once_a_scrape_has_happened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scrape on turn 1 → scrapes_used > 0 → the turn-2 emit is accepted with
    # no further forcing (regression guard for the happy path).
    provider = _install(monkeypatch, responses=[
        _msg([_scrape("https://gmauthority.com/x")]),
        _msg([_emit([_FINDING])]),
    ])
    out = await agentic.run_specialist_agentic("cmo", _FakeAgent(), "CTX")
    assert len(out) == 1
    assert provider.scrape_calls["n"] == 1
    assert len(provider.calls) == 2  # accepted on the emit turn, no re-loop


@pytest.mark.asyncio
async def test_premature_emit_accepted_at_iteration_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # On the final allowed iteration there's no room to force a read, so a
    # 0-scrape emit is accepted as the safety valve (don't lose everything).
    monkeypatch.setenv("RESEARCH_LOOP_MAX_ITERATIONS", "1")
    provider = _install(monkeypatch, responses=[_msg([_emit([_FINDING])])])
    out = await agentic.run_specialist_agentic("gc", _FakeAgent(), "CTX")
    assert len(out) == 1
    assert provider.scrape_calls["n"] == 0
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_scrape_budget_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_SCRAPE_MAX_PER_SPECIALIST", "1")
    provider = _install(monkeypatch, responses=[
        _msg([_scrape("https://a.example", "s1")]),
        _msg([_scrape("https://b.example", "s2")]),
        _msg([_emit([_FINDING])]),
    ])
    out = await agentic.run_specialist_agentic("coo", _FakeAgent(), "CTX")
    assert len(out) == 1
    # Only the first scrape consumed the budget; the second got the refusal.
    assert provider.scrape_calls["n"] == 1
    second_scrape_result = provider.calls[2]["messages"][-1]["content"][0]
    assert "budget exhausted" in second_scrape_result["content"].lower()


@pytest.mark.asyncio
async def test_no_scrape_no_emit_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _install(monkeypatch, responses=[_msg([_text("nothing found")])])
    out = await agentic.run_specialist_agentic("gc", _FakeAgent(), "CTX")
    assert out == []
    assert len(provider.calls) == 1  # stopped, did not loop


@pytest.mark.asyncio
async def test_provider_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, responses=[RuntimeError("boom")])
    out = await agentic.run_specialist_agentic("cmo", _FakeAgent(), "CTX")
    assert out == []


@pytest.mark.asyncio
async def test_iteration_cap_without_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_LOOP_MAX_ITERATIONS", "2")
    provider = _install(monkeypatch, responses=[
        _msg([_scrape("https://a.example", "s1")]),
        _msg([_scrape("https://b.example", "s2")]),
        _msg([_scrape("https://c.example", "s3")]),  # never reached
    ])
    out = await agentic.run_specialist_agentic("cpo", _FakeAgent(), "CTX")
    assert out == []
    assert len(provider.calls) == 2  # capped at 2 iterations


def test_assistant_turn_echoes_thinking_and_collects_scrape() -> None:
    # thinking blocks MUST be preserved in the assistant turn (extended
    # reasoning) or the next API call 400s; scrape_url must be collected.
    thinking = SimpleNamespace(
        type="thinking",
        model_dump=lambda exclude_none=True: {
            "type": "thinking", "thinking": "reasoning...",
        },
    )
    content, scrape_calls = agentic._assistant_turn(
        [thinking, _scrape("https://x.example", "s9"), _text("note")]
    )
    # Order preserved: thinking must precede the tool_use it reasoned about
    # (Anthropic rejects a turn where tool_use comes before its thinking).
    assert content[0]["type"] == "thinking"
    assert [c["id"] for c in scrape_calls] == ["s9"]


# --------------------------------------------------------------------- #
# scrape_tool handler
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_handle_scrape_url_budget_exhausted() -> None:
    out = await scrape_tool.handle_scrape_url({"url": "https://x"}, budget_remaining=0)
    assert "budget exhausted" in out.lower()


@pytest.mark.asyncio
async def test_handle_scrape_url_bad_url() -> None:
    out = await scrape_tool.handle_scrape_url({"url": "not-a-url"}, budget_remaining=3)
    assert out.startswith("error")


@pytest.mark.asyncio
async def test_handle_scrape_url_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def none_scrape(url: str) -> str | None:
        return None

    monkeypatch.setattr(scrape_tool.xcrawl_client, "scrape", none_scrape)
    out = await scrape_tool.handle_scrape_url(
        {"url": "https://dead.example"}, budget_remaining=3,
    )
    assert "could not read" in out.lower()


@pytest.mark.asyncio
async def test_handle_scrape_url_caps_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    big = "x" * 50_000

    async def big_scrape(url: str) -> str | None:
        return big

    monkeypatch.setattr(scrape_tool.xcrawl_client, "scrape", big_scrape)
    out = await scrape_tool.handle_scrape_url(
        {"url": "https://big.example"}, budget_remaining=3,
    )
    assert len(out) == scrape_tool._SCRAPE_RESULT_CHARS


# --------------------------------------------------------------------- #
# Dispatch branch in research_one_specialist
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_branch_uses_agentic_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    monkeypatch.setenv("XCRAWL_API_KEY", "dummy")
    monkeypatch.setenv("RESEARCH_AGENTIC_SCRAPE_ENABLED", "true")
    sentinel: list[Any] = []

    async def fake_agentic(slug: str, agent: Any, ctx: str) -> list[Any]:
        sentinel.append(slug)
        return ["AGENTIC"]  # type: ignore[list-item]

    monkeypatch.setattr(agentic, "run_specialist_agentic", fake_agentic)
    out = await sr.research_one_specialist("cso", _FakeAgent(), "CTX")
    assert out == ["AGENTIC"]
    assert sentinel == ["cso"]


@pytest.mark.asyncio
async def test_branch_single_shot_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_AGENTIC_SCRAPE_ENABLED", "false")

    async def boom_agentic(*a: Any, **k: Any) -> list[Any]:
        raise AssertionError("must use single-shot when disabled")

    monkeypatch.setattr(agentic, "run_specialist_agentic", boom_agentic)

    class _SingleShotAgent:
        def effective_system_prompt(self) -> str:
            return "P"

        async def analyze_with_tools(self, *a: Any, **k: Any) -> Any:
            return _msg([_emit([_FINDING])])

    out = await sr.research_one_specialist("cfo", _SingleShotAgent(), "CTX")
    assert len(out) == 1 and out[0].title == _FINDING["title"]
