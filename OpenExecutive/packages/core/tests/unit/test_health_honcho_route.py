"""GET /health/honcho probes the active Honcho workspace with an authed SDK call."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import health as health_route


@pytest.fixture(autouse=True)
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("EXEC_EMAIL_ADDRESS", "exec@example.com")
    for k in ("HONCHO_ENABLED", "HONCHO_API_KEY", "HONCHO_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(health_route.router)
    return TestClient(app)


def test_disabled_returns_disabled_status() -> None:
    resp = _app().get("/health/honcho")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "disabled"


def test_client_construction_failure_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONCHO_ENABLED", "true")
    monkeypatch.setenv("HONCHO_API_KEY", "k")
    monkeypatch.setenv("HONCHO_BASE_URL", "https://fake")

    from openexecutive.memory import honcho_client as honcho_mod

    async def _none() -> None:
        return None

    monkeypatch.setattr(honcho_mod, "_get_client", _none)

    resp = _app().get("/health/honcho")
    body = resp.json()
    assert body["status"] == "error"
    assert body["error_type"] == "ClientConstructionFailed"
    assert "latency_ms" in body


def test_reachable_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONCHO_ENABLED", "true")
    monkeypatch.setenv("HONCHO_API_KEY", "k")
    monkeypatch.setenv("HONCHO_BASE_URL", "https://fake")

    class _Aio:
        async def get_metadata(self) -> dict:
            return {}

    class _Client:
        aio = _Aio()

    from openexecutive.memory import honcho_client as honcho_mod

    async def _client() -> _Client:
        return _Client()

    monkeypatch.setattr(honcho_mod, "_get_client", _client)

    resp = _app().get("/health/honcho")
    body = resp.json()
    assert body["status"] == "ok"
    assert "latency_ms" in body
    assert "http_status" not in body  # old field is gone


def test_sdk_error_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONCHO_ENABLED", "true")
    monkeypatch.setenv("HONCHO_API_KEY", "k")
    monkeypatch.setenv("HONCHO_BASE_URL", "https://fake")

    class _Aio:
        async def get_metadata(self) -> dict:
            raise RuntimeError("nope")

    class _Client:
        aio = _Aio()

    from openexecutive.memory import honcho_client as honcho_mod

    async def _client() -> _Client:
        return _Client()

    monkeypatch.setattr(honcho_mod, "_get_client", _client)

    resp = _app().get("/health/honcho")
    body = resp.json()
    assert body["status"] == "error"
    assert body["error_type"] == "RuntimeError"
    assert "nope" in body["error_msg"]
