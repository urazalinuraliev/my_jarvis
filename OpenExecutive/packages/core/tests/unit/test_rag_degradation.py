"""A broken vector store costs a turn its grounding, never the turn itself.

Retrieval and the skill/MCP tools all read ChromaDB. Before this, a corrupt or
locked store raised straight through `retrieve()` — or through one tool
handler inside the turn's `asyncio.gather` — and the user got an error instead
of an answer. Every other context source in the chat route already degrades to
an empty string, so these do too.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from openexecutive.audit.logger import AuditLogger, set_audit_logger
from openexecutive.knowledge import retriever as retriever_mod
from openexecutive.knowledge import store as store_mod
from openexecutive.knowledge.retriever import retrieve, retrieve_failures
from openexecutive.orchestrator.executive import _tool_results_or_errors

_QUERY = "What did we decide about pricing?"


@pytest.fixture(autouse=True)
def _temp_audit_db(tmp_path: Path) -> Iterator[None]:
    """Degraded retrieval and the tool loop both write audit rows — keep them
    out of the developer's real ./episodic_memory.db."""
    set_audit_logger(AuditLogger(tmp_path / "audit.db"))
    yield
    set_audit_logger(None)


class PanicException(BaseException):
    """Stand-in for pyo3_runtime.PanicException (matched by class name)."""


@pytest.fixture
def fake_review_store() -> SimpleNamespace:
    return SimpleNamespace(
        get_rejected_filenames=lambda _ct: set(),
        get_rejected_source_ids=lambda: set(),
        get_priority_map=lambda _ct: {},
        list_annotations=lambda domains=None, active_only=True: [],
    )


def _store_raising(exc: BaseException) -> MagicMock:
    store = MagicMock()
    store.query.side_effect = exc
    return store


def test_retrieve_degrades_when_the_store_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store is built inside retrieve() when the caller passes none.

    The logger is captured by replacing its method rather than with caplog:
    the app's logging config turns propagation off, so caplog sees nothing
    once anything has imported it (the full suite, but not this file alone).
    """
    logged: list[str] = []

    def boom(self: Any, persist_directory: Any = "./chroma_db") -> None:
        raise RuntimeError("ChromaDB panicked opening ./chroma_db")

    monkeypatch.setattr(store_mod.ChromaDBStore, "__init__", boom)
    monkeypatch.setattr(
        retriever_mod.logger,
        "exception",
        lambda msg, *args, **_kw: logged.append(msg % args if args else msg),
    )

    assert retrieve(query=_QUERY) == ""
    assert logged and logged[0].startswith("retrieve failed")


@pytest.mark.parametrize(
    "exc", [RuntimeError("database disk image is malformed"), PanicException("index corrupted")]
)
def test_retrieve_degrades_when_a_query_fails(
    fake_review_store: SimpleNamespace, exc: BaseException
) -> None:
    """Both a plain failure and a Rust panic from the bindings degrade."""
    assert retrieve(query=_QUERY, store=_store_raising(exc), review_store=fake_review_store) == ""


def test_retrieve_never_swallows_cancellation(fake_review_store: SimpleNamespace) -> None:
    """The route cancels this call on the turn timeout — it must still unwind."""
    with pytest.raises(asyncio.CancelledError):
        retrieve(
            query=_QUERY,
            store=_store_raising(asyncio.CancelledError()),
            review_store=fake_review_store,
        )


def test_retrieve_failures_degrades_too() -> None:
    store = _store_raising(RuntimeError("file is not a database"))
    assert retrieve_failures(query=_QUERY, store=store) == ""


def test_a_failed_retrieval_still_leaves_an_audit_row(
    fake_review_store: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the flow chart and the debug panel show "0 chunks", which
    reads exactly like "the store had nothing relevant"."""
    rows: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        retriever_mod,
        "_audit_log",
        lambda event, summary, **kw: rows.append((event, summary, kw.get("details", {}))),
    )

    retrieve(
        query=_QUERY,
        specialist_name="cmo",
        store=_store_raising(RuntimeError("index corrupted")),
        review_store=fake_review_store,
    )

    assert rows and rows[0][0] == "knowledge_retrieval"
    event, summary, details = rows[0]
    # The summary and details.error are what the audit list and the session
    # flow chart show; "0 chunks" alone would read as "found nothing".
    assert "failed (RuntimeError)" in summary
    assert details["error"] == "RuntimeError"
    assert details["specialist"] == "cmo"


def test_a_successful_retrieval_is_not_marked_failed(
    fake_review_store: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        retriever_mod,
        "_audit_log",
        lambda _event, summary, **kw: rows.append((summary, kw.get("details", {}))),
    )
    store = MagicMock()
    store.query.return_value = []

    retrieve(query=_QUERY, store=store, review_store=fake_review_store)

    summary, details = rows[0]
    assert "0 chunks" in summary
    assert details["error"] is None


def test_the_flow_chart_node_names_a_failed_retrieval() -> None:
    """The audit graph node is built from details, not from the summary."""
    from openexecutive.api.routes.audit import _node_label

    failed = _node_label(
        "knowledge_retrieval", "", {"domain_filter": ["marketing"], "error": "PanicException"}
    )
    healthy = _node_label(
        "knowledge_retrieval", "", {"domain_filter": ["marketing"], "builtin_count": 3}
    )

    assert failed == "RAG[marketing] · failed (PanicException)"
    assert healthy == "RAG[marketing] · 3 chunks"


def test_tool_batch_keeps_the_results_of_the_tools_that_worked() -> None:
    results = _tool_results_or_errors(
        ["search_skills", "load_skill"],
        [RuntimeError("chroma is down"), "# positioning-statement"],
    )

    assert json.loads(results[0])["error"].startswith("search_skills failed")
    assert results[1] == "# positioning-statement"


def test_tool_error_tells_the_model_not_to_retry() -> None:
    """Side-effecting tools live in the same batch: the handler may have posted
    the message and then raised, so a retry could repeat the side effect."""
    results = _tool_results_or_errors(["post_to_slack"], [RuntimeError("boom")])

    payload = json.loads(results[0])
    assert payload["retry"].startswith("no")
    assert "boom" not in results[0]  # the exception text never reaches the model


def test_tool_batch_reports_a_panic_as_a_tool_error() -> None:
    results = _tool_results_or_errors(["search_skills"], [PanicException("index corrupted")])

    assert json.loads(results[0])["error"].startswith("search_skills failed")


def test_tool_batch_never_swallows_cancellation() -> None:
    with pytest.raises(asyncio.CancelledError):
        _tool_results_or_errors(["search_skills"], [asyncio.CancelledError()])


# --------------------------------------------------------------------- #
# Fake provider plumbing (mirrors test_executive_form_patch.py)
# --------------------------------------------------------------------- #


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id_: str, name: str, input_: dict[str, Any]) -> None:
        self.id = id_
        self.name = name
        self.input = input_


class _FinalMsg:
    def __init__(self, content: list[Any], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


class _FakeStream:
    def __init__(self, final_msg: _FinalMsg) -> None:
        self._final = final_msg

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def get_final_message(self) -> _FinalMsg:
        return self._final


class _ScriptedProvider:
    def __init__(self, final_msgs: list[_FinalMsg]) -> None:
        self._msgs = list(final_msgs)
        self.calls: list[dict[str, Any]] = []

    def messages_stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        return _FakeStream(self._msgs.pop(0))


def test_a_failing_skill_tool_does_not_end_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every skill tool reads ChromaDB; one raising used to sink the answer.

    The model must get the failure as that tool's result and keep going.
    """
    from openexecutive.orchestrator import executive as exec_mod

    async def broken_search(_input: dict[str, Any]) -> str:
        raise RuntimeError("file is not a database")

    monkeypatch.setitem(exec_mod._ALL_SKILL_HANDLERS, "search_skills", broken_search)

    provider = _ScriptedProvider([
        _FinalMsg(
            [_ToolUseBlock("tu-1", "search_skills", {"query": "ad angles"})],
            stop_reason="tool_use",
        ),
        _FinalMsg([_TextBlock("Here is what I can say without the skill.")], stop_reason="end_turn"),
    ])

    async def run() -> list[Any]:
        with monkeypatch.context() as m:
            m.setattr(exec_mod, "get_provider", lambda *_a, **_kw: provider)
            return [
                item
                async for item in exec_mod.Executive()._stream_agent_loop(
                    system_blocks=[],
                    messages=[{"role": "user", "content": "find me an ad angle"}],
                    model="claude-test",
                )
            ]

    asyncio.run(run())

    tool_result = provider.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "tu-1"
    assert json.loads(tool_result["content"])["error"].startswith("search_skills failed")
