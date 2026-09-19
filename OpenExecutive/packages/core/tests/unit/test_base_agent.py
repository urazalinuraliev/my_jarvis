"""Unit tests for BaseAgent.analyze — verifies the user-turn block layout.

The Anthropic client is patched so no real API call is made.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from openexecutive.agents.base import BaseAgent  # noqa: E402


class _Dummy(BaseAgent):
    name = "dummy"
    domain = "strategy"
    model = "claude-test"
    use_deep_reasoning = False

    def get_system_prompt(self) -> str:
        return "You are a dummy specialist."


def _fake_text_response(text: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _capture_create() -> tuple[AsyncMock, object]:
    """Patch the provider registry so messages_create captures kwargs."""
    create_mock = AsyncMock(return_value=_fake_text_response())
    fake_provider = SimpleNamespace(messages_create=create_mock)
    return create_mock, fake_provider


def _run_analyze(**kwargs: str) -> AsyncMock:
    create_mock, fake_provider = _capture_create()
    with patch("openexecutive.agents.base.get_provider", return_value=fake_provider):
        asyncio.run(_Dummy().analyze(query="What should we do?", **kwargs))
    return create_mock


def test_analyze_includes_past_decisions_block_when_episodic_context_given() -> None:
    create_mock = _run_analyze(episodic_context="Recent decisions:\n- 2026-01-01 [strategy]: Expand to EU")
    user_content = create_mock.await_args.kwargs["messages"][0]["content"]
    assert "<past_decisions>" in user_content
    assert "Expand to EU" in user_content
    assert "</past_decisions>" in user_content


def test_analyze_omits_past_decisions_block_when_empty() -> None:
    create_mock = _run_analyze(episodic_context="")
    user_content = create_mock.await_args.kwargs["messages"][0]["content"]
    assert "<past_decisions>" not in user_content


def test_analyze_block_order_past_decisions_outermost() -> None:
    """Block order in user turn: <past_decisions> > <relevant_knowledge> > <conversation_context> > query.

    The model reads top-down; episodic memory frames everything that follows.
    """
    create_mock = _run_analyze(
        episodic_context="EPISODIC",
        retrieved_knowledge="KNOWLEDGE",
        context="CONTEXT",
    )
    content = create_mock.await_args.kwargs["messages"][0]["content"]
    past_idx = content.index("<past_decisions>")
    knowledge_idx = content.index("<relevant_knowledge>")
    context_idx = content.index("<conversation_context>")
    query_idx = content.index("What should we do?")
    assert past_idx < knowledge_idx < context_idx < query_idx


def test_analyze_works_with_only_query() -> None:
    """No optional context — user turn is just the query."""
    create_mock = _run_analyze()
    content = create_mock.await_args.kwargs["messages"][0]["content"]
    assert content == "What should we do?"


class _DeepDummy(BaseAgent):
    """Chat-time defaults: deep reasoning on a pricey model."""

    name = "deep_dummy"
    domain = "strategy"
    model = "claude-opus-expensive"
    use_deep_reasoning = True

    def get_system_prompt(self) -> str:
        return "You are a deep specialist."


def _run_analyze_with_tools(**kwargs: object) -> AsyncMock:
    create_mock, fake_provider = _capture_create()
    with patch("openexecutive.agents.base.get_provider", return_value=fake_provider):
        asyncio.run(
            _DeepDummy().analyze_with_tools(
                "research this", tools=[{"name": "t"}], **kwargs
            )
        )
    return create_mock


def test_analyze_with_tools_uses_instance_defaults_when_no_override() -> None:
    """Without overrides, the agent's own model + deep-reasoning apply."""
    create_mock = _run_analyze_with_tools()
    kwargs = create_mock.await_args.kwargs
    assert kwargs["model"] == "claude-opus-expensive"
    assert "thinking" in kwargs  # deep reasoning on


def test_analyze_with_tools_model_and_deep_reasoning_overrides_apply() -> None:
    """The research fan-out pins a cheaper model + deep reasoning off for one
    turn without disturbing the agent's chat-time defaults."""
    create_mock = _run_analyze_with_tools(
        model_override="claude-cheap-research",
        deep_reasoning_override=False,
    )
    kwargs = create_mock.await_args.kwargs
    assert kwargs["model"] == "claude-cheap-research"
    assert "thinking" not in kwargs  # deep reasoning off → no adaptive thinking
