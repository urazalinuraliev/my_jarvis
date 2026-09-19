"""Audit context manager — must survive async generators whose iteration
crosses asyncio Task boundaries.

Regression: when ``set_turn`` used ``ContextVar.set()`` + ``reset(token)``,
the Token validation raised ``ValueError: <Token …> was created in a
different Context`` whenever the wrapped ``async for`` over a streaming
generator resumed inside a different Task than the one that called
``__enter__``. This shows up on the FastAPI SSE path and on the httpx-
backed OpenRouter provider's streaming dispatch.

The fix saves the prior value and restores it on exit, which is
Context-independent.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from openexecutive.audit.context import (
    get_active_ids,
    set_turn,
)


def test_set_turn_binds_and_restores_prior_values() -> None:
    """Outside the block both vars are None; inside they reflect the kwargs;
    after the block they restore to the prior values (None here)."""
    assert get_active_ids() == (None, None)
    with set_turn(session_id="s1", turn_id="t1"):
        assert get_active_ids() == ("s1", "t1")
    assert get_active_ids() == (None, None)


def test_set_turn_nests_and_restores_outer_values() -> None:
    """Nested ``set_turn`` blocks must restore the outer values on exit —
    a workflow that opens a sub-turn for a tool call must not stomp the
    caller's turn id."""
    with set_turn(session_id="outer-s", turn_id="outer-t"):
        with set_turn(session_id="inner-s", turn_id="inner-t"):
            assert get_active_ids() == ("inner-s", "inner-t")
        # Inner block exits → outer ids restored.
        assert get_active_ids() == ("outer-s", "outer-t")
    assert get_active_ids() == (None, None)


def test_set_turn_survives_async_generator_resumed_across_tasks() -> None:
    """The exact failure mode the user hit: a ``with set_turn(...)`` block
    has its ``__enter__`` and ``__exit__`` run in different asyncio
    ``Context`` instances. Pre-fix, ``ContextVar.reset(token)`` raised
    ``ValueError: <Token …> was created in a different Context``.

    We provoke this directly with ``contextvars.copy_context()`` rather
    than indirectly through asyncio task scheduling — copy_context is
    the underlying primitive every async runtime uses to give a new
    task its own Context, and it gives us deterministic reproduction
    of the boundary without depending on FastAPI / httpx / anyio
    internals.
    """
    import contextvars

    # Drive __enter__ in Context A, __exit__ in Context B. Pre-fix, the
    # finally-branch ``reset(token)`` blows up because the Token was
    # created in A but reset is being called from B.
    cm = set_turn(session_id="cross-ctx-s", turn_id="cross-ctx-t")
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()

    ctx_a.run(cm.__enter__)
    # Generator's ``__exit__`` accepts the (exc_type, exc, tb) triple.
    ctx_b.run(cm.__exit__, None, None, None)

    # Outside both contexts, the live default Context is untouched.
    assert get_active_ids() == (None, None)


def test_set_turn_partial_kwargs_pass_none_for_unset_field() -> None:
    """Either kwarg can be set independently — workflows that have a
    session but no logical turn pass just ``session_id``."""
    with set_turn(session_id="only-session"):
        assert get_active_ids() == ("only-session", None)
    with set_turn(turn_id="only-turn"):
        assert get_active_ids() == (None, "only-turn")


def test_set_turn_exit_runs_even_on_exception() -> None:
    """A streaming consumer that raises mid-iteration must not leak
    the bound ids — the ``finally`` branch restores prior values."""
    with pytest.raises(RuntimeError, match="boom"):
        with set_turn(session_id="leaky-s", turn_id="leaky-t"):
            assert get_active_ids() == ("leaky-s", "leaky-t")
            raise RuntimeError("boom")
    assert get_active_ids() == (None, None)
