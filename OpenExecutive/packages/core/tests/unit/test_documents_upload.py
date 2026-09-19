"""Unit tests for POST /documents — domain must come from the multipart form.

Regression guard: `domain` was declared as a bare default (`domain: str =
"general"`), which FastAPI parses as a query parameter. The UI sends it as a
form field, so it was silently dropped and every upload landed under
"general" — invisible to domain-filtered specialist retrieval.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import documents


class _CapturingStore:
    """Records the metadata passed to add_documents so the test can assert
    the domain tag without standing up a real ChromaDB / embedding model."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str,
    ) -> None:
        self.added.extend(metadatas)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("COMPANY_PROFILE_PATH", str(tmp_path / "company" / "profile.yaml"))
    # Don't fan out to the real proactive-alerts pipeline during the test.
    monkeypatch.setattr(
        "openexecutive.alerts.pipeline.schedule_evaluation",
        lambda *a, **k: None,
    )

    app = FastAPI()
    app.include_router(documents.router)
    app.state.store = _CapturingStore()
    return TestClient(app)


def _upload(client: TestClient, **data: str) -> Any:
    files = {"file": ("plan.md", io.BytesIO(b"# Plan\nGrow revenue 30%."), "text/markdown")}
    return client.post("/documents", files=files, data=data)


def test_domain_from_form_field_is_honored(client: TestClient) -> None:
    resp = _upload(client, domain="finance")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["domain"] == "finance"
    assert body["chunks_indexed"] >= 1

    store: _CapturingStore = client.app.state.store  # type: ignore[attr-defined]
    assert store.added, "expected at least one indexed chunk"
    assert all(m["domain"] == "finance" for m in store.added)


def test_domain_defaults_to_general_when_omitted(client: TestClient) -> None:
    resp = _upload(client)

    assert resp.status_code == 200, resp.text
    assert resp.json()["domain"] == "general"
    store: _CapturingStore = client.app.state.store  # type: ignore[attr-defined]
    assert all(m["domain"] == "general" for m in store.added)


def test_get_document_returns_extracted_text(client: TestClient) -> None:
    # Upload writes the original file to disk; the viewer reads it back.
    assert _upload(client).status_code == 200

    resp = client.get("/documents/plan.md")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "plan.md"
    assert "Grow revenue 30%." in body["content"]


def test_get_document_missing_returns_404(client: TestClient) -> None:
    resp = client.get("/documents/does_not_exist.md")
    assert resp.status_code == 404


def test_get_document_rejects_dotfile(client: TestClient) -> None:
    # The filename guard rejects dotfiles / non-bare names so a crafted path
    # can't escape the docs directory. (URL-encoded `../` is additionally
    # collapsed by path normalization before it ever reaches the handler.)
    resp = client.get("/documents/.env")
    assert resp.status_code == 400
