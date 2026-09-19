"""Tests for the CrewAI marketing-crew bridge: adapter, chat tool, Telegram path.

No crew ever runs for real: the crew repo is a temp dir and the crew module
is a fake injected into sys.modules.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import BackgroundTasks

from openexecutive.integrations import crewai_adapter, telegram_bot
from openexecutive.integrations.adapters import AgentResult
from openexecutive.integrations.crewai_adapter import (
    INSTAGRAM_OUTPUT_FILES,
    CrewAIAdapter,
    crew_unavailable_reason,
    resolve_crew_model,
)
from openexecutive.orchestrator import crewai_tools

# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("crewai_model", "default_model", "anthropic_direct", "expected"),
    [
        ("openai/gpt-5", "claude-sonnet-5", True, "openai/gpt-5"),
        (None, "claude-sonnet-5", True, "anthropic/claude-sonnet-5"),
        # OE routes this Claude model via OpenRouter / a local backend.
        (None, "claude-sonnet-5", False, None),
        # OpenRouter / local slugs would be misrouted by CrewAI: not guessed.
        (None, "anthropic/claude-opus-5", True, None),
        (None, "llama3.3", True, None),
    ],
)
def test_resolve_crew_model(
    crewai_model: str | None, default_model: str, anthropic_direct: bool, expected: str | None
) -> None:
    assert (
        resolve_crew_model(crewai_model, default_model, anthropic_direct=anthropic_direct)
        == expected
    )


def test_commented_repo_path_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # dotenv keeps an inline comment as the value when it follows "KEY=   ".
    monkeypatch.setenv("CREWAI_REPO_PATH", "# path to the crew checkout")
    assert crewai_adapter.crew_repo_path() == crewai_adapter._default_crew_repo()


def _crew_repo(root: Path, *, with_crew_llm: bool = True) -> Path:
    (root / "src").mkdir(parents=True)
    if with_crew_llm:
        (root / "src" / "crew_llm.py").write_text("", encoding="utf-8")
    return root


def test_crew_unavailable_when_repo_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CREWAI_REPO_PATH", str(tmp_path / "nowhere"))
    reason = crew_unavailable_reason()
    assert reason is not None
    assert "nowhere" in reason


def test_crew_unavailable_for_an_unmodified_upstream_clone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREWAI_REPO_PATH", str(_crew_repo(tmp_path, with_crew_llm=False)))
    monkeypatch.setattr(crewai_adapter, "find_spec", lambda name: object())
    reason = crew_unavailable_reason()
    assert reason is not None and "crew_llm.py" in reason


def test_crew_available_when_repo_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CREWAI_REPO_PATH", str(_crew_repo(tmp_path)))
    monkeypatch.setattr(crewai_adapter, "find_spec", lambda name: object())
    assert crew_unavailable_reason() is None


def test_unknown_crew_rejected() -> None:
    with pytest.raises(ValueError):
        CrewAIAdapter(crew="tiktok")


# ---------------------------------------------------------------------------
# Instagram crew run (fake crew module)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_instagram_crew(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A crew repo on disk plus a fake ``instagram.crew`` module; records kickoff inputs."""
    repo = _crew_repo(tmp_path / "crew-repo")
    monkeypatch.setenv("CREWAI_REPO_PATH", str(repo))
    monkeypatch.setattr(crewai_adapter, "find_spec", lambda name: object())
    monkeypatch.setattr(sys, "path", list(sys.path))  # undo the adapter's append
    # Register the env var the adapter writes so teardown removes it again.
    monkeypatch.setenv("CREWAI_DISABLE_TELEMETRY", "")
    monkeypatch.delenv("CREWAI_DISABLE_TELEMETRY")
    monkeypatch.delenv("CREWAI_MODEL", raising=False)

    settings = SimpleNamespace(
        crewai_model=None,
        default_model="claude-sonnet-5",
        anthropic_api_key="sk-test-not-used",
        openrouter_enabled=False,
        openrouter_api_key="sk-or-test",
        local_models_enabled=False,
        local_models=[],
        crew_output_dir=tmp_path / "runs",
        user_timezone="UTC",
    )
    monkeypatch.setattr("openexecutive.config.get_settings", lambda: settings)

    seen: dict[str, Any] = {"settings": settings}

    crew_llm = types.ModuleType("crew_llm")
    crew_llm.configure = lambda **kw: seen.__setitem__("configured", kw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "crew_llm", crew_llm)

    class _FakeCrew:
        async def kickoff_async(self, inputs: dict[str, Any]) -> str:
            seen["inputs"] = inputs
            out = Path(inputs["output_dir"])
            for name in INSTAGRAM_OUTPUT_FILES:
                (out / name).write_text(f"# {name}", encoding="utf-8")
            return "FINAL REPORT"

    class InstagramCrew:
        def crew(self) -> _FakeCrew:
            return _FakeCrew()

    package = types.ModuleType("instagram")
    module = types.ModuleType("instagram.crew")
    module.InstagramCrew = InstagramCrew  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "instagram", package)
    monkeypatch.setitem(sys.modules, "instagram.crew", module)
    seen["runs_dir"] = settings.crew_output_dir
    return seen


async def test_instagram_run_writes_into_its_own_run_dir(fake_instagram_crew: dict[str, Any]) -> None:
    result = await CrewAIAdapter(crew="instagram").run(task="summer launch")

    inputs = fake_instagram_crew["inputs"]
    run_dir = Path(inputs["output_dir"])
    assert run_dir.parent == fake_instagram_crew["runs_dir"]
    assert inputs["topic_of_the_week"] == "summer launch"
    assert inputs["instagram_description"] == "summer launch"
    date.fromisoformat(inputs["current_date"])  # a real date, not ""

    assert result.text == "FINAL REPORT"
    assert [f["name"] for f in result.files] == list(INSTAGRAM_OUTPUT_FILES)
    for file in result.files:
        assert Path(file["path"]).is_file()
        assert Path(file["path"]).parent == run_dir

    # Model and key go to the crew in-process, never into os.environ.
    assert fake_instagram_crew["configured"] == {
        "model": "anthropic/claude-sonnet-5",
        "api_key": "sk-test-not-used",
    }
    assert "CREWAI_MODEL" not in os.environ
    assert os.environ["CREWAI_DISABLE_TELEMETRY"] == "true"


@pytest.mark.parametrize(
    ("crewai_model", "expected_key"),
    [
        ("openrouter/some-model", "sk-or-test"),
        ("claude-sonnet-5", "sk-test-not-used"),  # CrewAI calls Anthropic for bare claude-*
        ("openai/gpt-5", None),  # a key OE doesn't hold: CrewAI reads it from the env
    ],
)
async def test_crewai_model_override_gets_its_providers_key(
    fake_instagram_crew: dict[str, Any], crewai_model: str, expected_key: str | None
) -> None:
    fake_instagram_crew["settings"].crewai_model = crewai_model
    await CrewAIAdapter(crew="instagram").run(task="x")
    assert fake_instagram_crew["configured"] == {"model": crewai_model, "api_key": expected_key}


@pytest.mark.parametrize(
    "routing",
    [
        {"default_model": "llama3.3"},
        {"openrouter_enabled": True},
        {"local_models_enabled": True, "local_models": ["claude-sonnet-5"]},
    ],
)
async def test_default_model_not_sent_to_anthropic_requires_crewai_model(
    fake_instagram_crew: dict[str, Any], routing: dict[str, Any]
) -> None:
    for key, value in routing.items():
        setattr(fake_instagram_crew["settings"], key, value)
    with pytest.raises(RuntimeError, match="CREWAI_MODEL"):
        await CrewAIAdapter(crew="instagram").run(task="x")


async def test_two_instagram_runs_do_not_share_files(fake_instagram_crew: dict[str, Any]) -> None:
    first = await CrewAIAdapter(crew="instagram").run(task="a")
    second = await CrewAIAdapter(crew="instagram").run(task="b")
    assert first.files[0]["path"] != second.files[0]["path"]


async def test_run_raises_clear_error_without_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CREWAI_REPO_PATH", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="missing"):
        await CrewAIAdapter(crew="instagram").run(task="x")


# ---------------------------------------------------------------------------
# run_crew chat tool
# ---------------------------------------------------------------------------


@pytest.fixture
def run_records(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Capture workflow-run writes instead of hitting the real DB / audit log."""
    records: dict[str, list[Any]] = {"created": [], "completed": [], "failed": []}
    monkeypatch.setattr(crewai_tools, "create_run", lambda *a, **k: records["created"].append(a))
    monkeypatch.setattr(crewai_tools, "complete_run", lambda *a, **k: records["completed"].append(a))
    monkeypatch.setattr(crewai_tools, "fail_run", lambda *a, **k: records["failed"].append(a))
    monkeypatch.setattr(crewai_tools, "audit_log", lambda *a, **k: None)
    return records


async def _drain_background_runs() -> None:
    while crewai_tools._background_runs:
        await asyncio.gather(*crewai_tools._background_runs, return_exceptions=True)


async def test_run_crew_rejects_bad_input(run_records: dict[str, list[Any]]) -> None:
    assert "error" in json.loads(await crewai_tools.handle_run_crew({"crew": "instagram", "task": ""}))
    out = json.loads(await crewai_tools.handle_run_crew({"crew": "tiktok", "task": "x"}))
    assert "unknown crew" in out["error"]
    assert run_records["created"] == []


async def test_run_crew_reports_unavailable_without_server_paths(
    run_records: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        crewai_adapter, "crew_unavailable_reason", lambda: "repo not found at /srv/secret"
    )
    out = json.loads(await crewai_tools.handle_run_crew({"crew": "instagram", "task": "x"}))
    assert "not installed" in out["error"]
    assert "/srv/secret" not in out["error"]


async def test_run_crew_returns_at_once_and_completes_the_run_later(
    run_records: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crew takes minutes — longer than a chat turn may last — so the tool
    starts it and returns; the run is completed when the crew ends."""
    monkeypatch.setattr(crewai_adapter, "crew_unavailable_reason", lambda: None)
    release = asyncio.Event()

    class _Adapter:
        async def run(self, *, task: str, context: str = "") -> AgentResult:
            await release.wait()
            return AgentResult(text="the report")

    monkeypatch.setattr(crewai_adapter, "get_crewai_adapter", lambda crew: _Adapter())
    out = json.loads(await crewai_tools.handle_run_crew({"crew": "instagram", "task": "x"}))
    assert out["status"] == "started"
    assert run_records["created"][0][0] == out["run_id"]
    assert run_records["completed"] == []  # still running

    release.set()
    await _drain_background_runs()
    assert run_records["completed"] == [(out["run_id"], "the report")]
    assert run_records["failed"] == []


async def test_run_crew_failure_is_recorded_not_returned(
    run_records: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crewai_adapter, "crew_unavailable_reason", lambda: None)

    class _Adapter:
        async def run(self, *, task: str, context: str = "") -> AgentResult:
            raise PermissionError("[Errno 13] Permission denied: '/app/crew_runs/x'")

    monkeypatch.setattr(crewai_adapter, "get_crewai_adapter", lambda crew: _Adapter())
    out = await crewai_tools.handle_run_crew({"crew": "instagram", "task": "x"})
    assert "/app/crew_runs" not in out  # the chat never sees the exception text
    await _drain_background_runs()
    [(run_id, error)] = run_records["failed"]
    assert run_id == json.loads(out)["run_id"]
    assert "Permission denied" in error


async def test_cancelled_crew_run_is_marked_failed(
    run_records: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server shutdown cancels the task: the run must not stay 'running' forever."""
    monkeypatch.setattr(crewai_adapter, "crew_unavailable_reason", lambda: None)

    class _Adapter:
        async def run(self, *, task: str, context: str = "") -> AgentResult:
            await asyncio.Event().wait()  # never finishes on its own
            raise AssertionError("unreachable")

    monkeypatch.setattr(crewai_adapter, "get_crewai_adapter", lambda crew: _Adapter())
    await crewai_tools.handle_run_crew({"crew": "instagram", "task": "x"})
    await asyncio.sleep(0)  # let the crew task start
    for background in list(crewai_tools._background_runs):
        background.cancel()
    await _drain_background_runs()
    assert len(run_records["failed"]) == 1
    assert "cancelled" in run_records["failed"][0][1]


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def telegram_outbox(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    box: dict[str, list[Any]] = {"messages": [], "documents": []}

    async def fake_send_message(token: str, chat_id: int, text: str) -> str | None:
        box["messages"].append(text)
        return "1"

    async def fake_send_document(token: str, chat_id: int, path: Path) -> bool:
        box["documents"].append(path.name)
        return True

    monkeypatch.setattr(telegram_bot, "send_message", fake_send_message)
    monkeypatch.setattr(telegram_bot, "send_document", fake_send_document)
    return box


def test_report_is_plain_text_and_preview_is_clipped() -> None:
    result = AgentResult(text="#sotuv_voronkasi **bold** " + "y" * 5000)
    preview = telegram_bot._format_crew_report(result, task="launch", preview=True)
    full = telegram_bot._format_crew_report(result, task="launch", preview=False)
    assert preview.startswith("Instagram content crew — topic: launch")
    assert "#sotuv_voronkasi **bold**" in preview  # sent verbatim, no parse mode
    assert len(preview) < 1700
    assert "y" * 5000 in full


def test_report_keeps_text_mentioning_final_output() -> None:
    result = AgentResult(text="Intro\n## Final Output\nCalendar")
    full = telegram_bot._format_crew_report(result, task="t", preview=False)
    assert "Intro" in full


async def test_report_attaches_files(telegram_outbox: dict[str, list[Any]], tmp_path: Path) -> None:
    report = tmp_path / "final-content-strategy.md"
    report.write_text("# report", encoding="utf-8")
    result = AgentResult(text="summary", files=[{"name": report.name, "path": str(report)}])
    await telegram_bot._deliver_crew_report(result, task="t", chat_id=1, token="tok")
    assert telegram_outbox["documents"] == [report.name]
    assert len(telegram_outbox["messages"]) == 1


async def test_report_falls_back_to_full_text_when_upload_fails(
    telegram_outbox: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "final-content-strategy.md"
    report.write_text("# report", encoding="utf-8")

    async def failing_document(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(telegram_bot, "send_document", failing_document)
    result = AgentResult(text="z" * 3000, files=[{"name": report.name, "path": str(report)}])
    await telegram_bot._deliver_crew_report(result, task="t", chat_id=1, token="tok")
    assert "z" * 3000 in telegram_outbox["messages"][-1]


async def test_send_document_network_error_reports_not_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A connection failure must return False (so the full-text fallback runs),
    not abort the whole delivery."""
    report = tmp_path / "final-content-strategy.md"
    report.write_text("# report", encoding="utf-8")

    class _Client:
        async def post(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(telegram_bot, "_get_http_client", lambda: _Client())
    assert await telegram_bot.send_document("tok", 1, report) is False


async def test_report_raises_when_nothing_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def rejected(*args: Any, **kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(telegram_bot, "send_message", rejected)
    with pytest.raises(RuntimeError):
        await telegram_bot._deliver_crew_report(AgentResult(text="x"), task="t", chat_id=1, token="tok")


class _FakeRequest:
    def __init__(self, text: str, chat_id: int) -> None:
        self.headers: dict[str, str] = {}
        self._body = {
            "message": {
                "message_id": 7,
                "chat": {"id": chat_id},
                "from": {"first_name": "Ann"},
                "text": text,
            }
        }

    async def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def telegram_webhook_env(
    monkeypatch: pytest.MonkeyPatch, telegram_outbox: dict[str, list[Any]]
) -> dict[str, list[Any]]:
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token="tok", telegram_webhook_secret=None),
    )
    monkeypatch.setattr(
        "openexecutive.people.store.find_person_by_telegram_chat_id", lambda chat_id: object()
    )
    monkeypatch.setattr(crewai_adapter, "crew_unavailable_reason", lambda: None)
    monkeypatch.setattr(telegram_bot, "_crew_runs_in_flight", set())
    return telegram_outbox


async def test_strategy_command_schedules_crew_with_bot_token(
    telegram_webhook_env: dict[str, list[Any]],
) -> None:
    tasks = BackgroundTasks()
    await telegram_bot.telegram_webhook(_FakeRequest("/strategy summer launch", 101), tasks)  # type: ignore[arg-type]
    assert len(tasks.tasks) == 1
    scheduled = tasks.tasks[0]
    assert scheduled.func is telegram_bot._run_crew_and_report
    assert scheduled.kwargs["token"] == "tok"
    assert scheduled.kwargs["task"] == "summer launch"
    assert telegram_webhook_env["messages"] == [telegram_bot._CREW_ACK_TEXT]
    assert 101 in telegram_bot._crew_runs_in_flight


async def test_back_to_back_strategy_commands_queue_one_crew(
    telegram_webhook_env: dict[str, list[Any]],
) -> None:
    """The second command arrives before the first's background task has run."""
    tasks = BackgroundTasks()
    await telegram_bot.telegram_webhook(_FakeRequest("/strategy one", 105), tasks)  # type: ignore[arg-type]
    await telegram_bot.telegram_webhook(_FakeRequest("/strategy two", 105), tasks)  # type: ignore[arg-type]
    assert len(tasks.tasks) == 1
    assert "already running" in telegram_webhook_env["messages"][-1]


async def test_strategy_command_refused_while_a_crew_runs(
    telegram_webhook_env: dict[str, list[Any]],
) -> None:
    telegram_bot._crew_runs_in_flight.add(102)
    tasks = BackgroundTasks()
    await telegram_bot.telegram_webhook(_FakeRequest("/strategy again", 102), tasks)  # type: ignore[arg-type]
    assert tasks.tasks == []
    assert "already running" in telegram_webhook_env["messages"][0]


async def test_strategy_command_when_crews_unavailable(
    telegram_webhook_env: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crewai_adapter, "crew_unavailable_reason", lambda: "no repo at /srv/x")
    tasks = BackgroundTasks()
    await telegram_bot.telegram_webhook(_FakeRequest("/marketing plan", 103), tasks)  # type: ignore[arg-type]
    assert tasks.tasks == []
    assert "isn't set up" in telegram_webhook_env["messages"][0]
    assert "/srv/x" not in telegram_webhook_env["messages"][0]  # no server paths to users


@pytest.mark.parametrize("crew_fails", [False, True])
async def test_crew_run_leaves_chat_free_and_clears_its_mark(
    monkeypatch: pytest.MonkeyPatch, telegram_outbox: dict[str, list[Any]], crew_fails: bool
) -> None:
    """A long crew run must not block the chat's ordinary Executive turns, and
    the chat can start another crew once this one ends — however it ends."""
    monkeypatch.setattr("openexecutive.audit.log_event", lambda *a, **k: None)
    monkeypatch.setattr(telegram_bot, "_crew_runs_in_flight", {104})
    observed: dict[str, bool] = {}

    class _Adapter:
        async def run(self, *, task: str, context: str = "") -> AgentResult:
            observed["chat_lock_held"] = telegram_bot._chat_lock(104).locked()
            observed["marked"] = 104 in telegram_bot._crew_runs_in_flight
            if crew_fails:
                raise RuntimeError("crew blew up")
            return AgentResult(text="done")

    monkeypatch.setattr(crewai_adapter, "get_crewai_adapter", lambda crew: _Adapter())
    await telegram_bot._run_crew_and_report(
        task="t", chat_id=104, token="tok", sender_name="Ann", message_id=1
    )
    assert observed == {"chat_lock_held": False, "marked": True}
    assert 104 not in telegram_bot._crew_runs_in_flight
    expected = "hit an error" if crew_fails else "done"
    assert expected in telegram_outbox["messages"][-1]
