"""Tests for the per-turn specialist fan-out cap.

`resolve_fanout_cap` resolves the cap (0/negative -> roster size, inert).
`partition_specialist_fanout` is the load-bearing wiring: it splits a turn's
consult_specialist tool_uses/calls at the cap and builds a skip-result for
EVERY over-cap tool_use (Anthropic requires one tool_result per tool_use).
"""
from __future__ import annotations

from openexecutive.config import get_settings
from openexecutive.orchestrator.router import (
    FANOUT_SKIP_MESSAGE,
    SPECIALIST_REGISTRY,
    partition_specialist_fanout,
    resolve_fanout_cap,
)

# ---- resolve_fanout_cap ---------------------------------------------------

def test_zero_falls_back_to_roster_size_inert() -> None:
    # 0 is the Settings default — must resolve to roster size so it's inert.
    assert resolve_fanout_cap(0) == len(SPECIALIST_REGISTRY)


def test_negative_falls_back_to_roster_size() -> None:
    assert resolve_fanout_cap(-5) == len(SPECIALIST_REGISTRY)


def test_positive_cap_is_honored() -> None:
    assert resolve_fanout_cap(3) == 3
    assert resolve_fanout_cap(1) == 1


def test_config_default_is_zero() -> None:
    # Guards the inert-by-default contract at the config layer.
    assert get_settings().max_parallel_specialists == 0


def test_skip_message_formats_with_cap() -> None:
    msg = FANOUT_SKIP_MESSAGE.format(cap=4)
    assert "cap=4" in msg
    assert "Skipped" in msg


# ---- partition_specialist_fanout (the executive-loop wiring) --------------

def _tu(i: int) -> dict:
    return {"id": f"id{i}", "name": "consult_specialist", "input": {}}


def _call(name: str) -> dict:
    return {"specialist": name, "query": "q", "context": ""}


def test_partition_under_cap_is_inert() -> None:
    tus = [_tu(0), _tu(1)]
    calls = [_call("cso"), _call("cfo")]
    run_tus, run_calls, skipped, cap = partition_specialist_fanout(tus, calls, 0)
    assert run_tus == tus
    assert run_calls == calls
    assert skipped == {}
    assert cap == len(SPECIALIST_REGISTRY)


def test_partition_over_cap_splits_and_skips_every_overflow() -> None:
    tus = [_tu(i) for i in range(4)]
    calls = [_call(n) for n in ("cso", "cfo", "chro", "gc")]
    run_tus, run_calls, skipped, cap = partition_specialist_fanout(tus, calls, 2)
    assert cap == 2
    # run lists stay aligned and equal length (the strict=True zip contract).
    assert len(run_tus) == len(run_calls) == 2
    assert [t["id"] for t in run_tus] == ["id0", "id1"]
    # EVERY over-cap tool_use id gets a skip result — no tool_use left without one.
    assert set(skipped) == {"id2", "id3"}
    assert all("cap=2" in v for v in skipped.values())


def test_partition_run_and_skipped_partition_all_tool_uses() -> None:
    # The union of dispatched + skipped must cover every tool_use id exactly once.
    tus = [_tu(i) for i in range(5)]
    calls = [_call("cso")] * 5
    run_tus, run_calls, skipped, cap = partition_specialist_fanout(tus, calls, 3)
    assert len(run_tus) == len(run_calls) == 3
    covered = {t["id"] for t in run_tus} | set(skipped)
    assert covered == {f"id{i}" for i in range(5)}
