"""Unit test for the eval runner's cancellation path.

Mocks the chat-runner factory so this test never touches Anthropic, Executive,
or the scenario YAML loader. We just verify the cancel-event plumbing:
  - setting the event mid-run causes the generator to emit `suite_canceled`
  - in-flight scenario tasks are cancelled within ~1s, not after their full work
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from openexecutive.evals import runner as runner_module


def test_cancel_event_stops_runner_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    # Replace the scenario loader so we don't read YAML from disk.
    fake_scenarios = [{"id": f"s{i}", "description": ""} for i in range(8)]
    monkeypatch.setattr(
        runner_module, "load_scenarios", lambda **_: fake_scenarios
    )

    # Replace the chat-runner factory with one whose `run_one` sleeps for a
    # long time — long enough that the test would time out unless cancel
    # actually cancels in-flight tasks.
    def fake_make_run_one(
        *,
        kind: str,
        store: Any,
        sem: asyncio.Semaphore,
        queue: asyncio.Queue[dict[str, Any] | None],
        passed: list[int],
        total: int,
        cancel_event: asyncio.Event | None,
    ) -> Any:
        async def run_one(i: int, scenario: dict[str, Any]) -> None:
            try:
                async with sem:
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    await queue.put(
                        {"type": "scenario_start", "scenario_id": scenario["id"]}
                    )
                    try:
                        await asyncio.sleep(30)  # would time out if not cancelled
                        await queue.put(
                            {
                                "type": "scenario_done",
                                "scenario_id": scenario["id"],
                                "passed": True,
                                "scores": {"overall": 5.0},
                            }
                        )
                    except asyncio.CancelledError:
                        return
            except asyncio.CancelledError:
                return

        return run_one

    monkeypatch.setattr(runner_module, "_make_run_one", fake_make_run_one)

    async def scenario() -> list[dict[str, Any]]:
        cancel_event = asyncio.Event()
        events: list[dict[str, Any]] = []

        async def consume() -> None:
            async for ev in runner_module.run_scenarios(
                kind="chat", cancel_event=cancel_event
            ):
                events.append(ev)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.1)  # let tasks spin up
        cancel_event.set()
        # Should finish well under the 30s sleep — generous 5s ceiling so a
        # slow CI runner doesn't flake.
        await asyncio.wait_for(consumer, timeout=5.0)
        return events

    events = asyncio.run(scenario())
    types = [e["type"] for e in events]
    assert types[0] == "suite_start"
    assert types[-1] == "suite_canceled"
    assert "suite_done" not in types
