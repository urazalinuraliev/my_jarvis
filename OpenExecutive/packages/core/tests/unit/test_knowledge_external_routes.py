"""Unit tests for the /knowledge/external API surface (Reference Library)."""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from fastapi.testclient import TestClient  # noqa: E402

from openexecutive.api.main import create_app  # noqa: E402
from openexecutive.knowledge import external_sources as oer  # noqa: E402


class _FakeChromaCollection:
    """Returns canned rows for `.get()` calls — emulates what /external needs."""

    def __init__(self, metadatas: list[dict[str, Any]], documents: list[str] | None = None):
        self._metadatas = metadatas
        self._documents = documents or [f"chunk-text-{i}" for i in range(len(metadatas))]

    def get(self, **kwargs: Any) -> dict[str, Any]:
        where = kwargs.get("where")
        limit = kwargs.get("limit")
        idxs = list(range(len(self._metadatas)))
        if isinstance(where, dict) and "source_id" in where:
            idxs = [i for i in idxs if self._metadatas[i].get("source_id") == where["source_id"]]
        if limit is not None:
            idxs = idxs[:limit]
        return {
            "metadatas": [self._metadatas[i] for i in idxs],
            "documents": [self._documents[i] for i in idxs],
        }


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeChromaCollection:
    """Inject a fake Chroma collection into the route's _get_store helper."""
    metadatas = [
        # Two OpenStax chunks + one GitLab chunk + one orphan with no source_id.
        {"source_id": "openstax-finance", "domain": "finance", "filename": "openstax-finance.pdf",
         "chunk_index": 0},
        {"source_id": "openstax-finance", "domain": "finance", "filename": "openstax-finance.pdf",
         "chunk_index": 1},
        {"source_id": "gitlab-handbook", "domain": "operations", "filename": "scaling.md",
         "chunk_index": 0},
        {"domain": "finance", "filename": "hand_written.md", "chunk_index": 0},
    ]
    col = _FakeChromaCollection(metadatas)
    fake = MagicMock()
    fake._client.get_collection.return_value = col

    monkeypatch.setattr(
        "openexecutive.api.routes.knowledge._get_store",
        lambda _request: fake,
    )
    return col


@pytest.fixture
def stub_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[oer.Source]:
    """Replace load_manifest with a tiny in-memory list pointed at tmp_path."""
    monkeypatch.setattr(oer, "EXTERNAL_CACHE_DIR", tmp_path)
    sources = [
        oer.Source(
            id="openstax-finance",
            title="Principles of Finance",
            publisher="OpenStax",
            license="CC BY 4.0",
            phase=1,
            domains=["finance"],
            type="openstax",
            url="https://openstax.org/details/books/principles-finance",
            slug="principles-finance",
        ),
        oer.Source(
            id="gitlab-handbook",
            title="GitLab Handbook",
            publisher="GitLab",
            license="MIT",
            phase=2,
            domains=["operations", "hr"],
            type="git",
            url="https://gitlab.com/gitlab-com/content-sites/handbook.git",
        ),
        oer.Source(
            id="not-yet-ingested",
            title="Future Source",
            publisher="x",
            license="CC0",
            phase=1,
            domains=["product"],
            type="pdf",
            url="https://example.invalid/x.pdf",
        ),
    ]
    # Touch a file in the finance cache dir so last_fetched_at returns a value.
    (tmp_path / "openstax-finance").mkdir()
    (tmp_path / "openstax-finance" / "openstax-finance.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(oer, "load_manifest", lambda *_a, **_k: sources)
    return sources


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_list_external_returns_all_manifest_sources_with_chunk_counts(
    client: TestClient, fake_store, stub_manifest
) -> None:
    r = client.get("/knowledge/external")
    assert r.status_code == 200
    body = r.json()

    assert body["total_chunks"] == 3  # excludes the chunk without source_id
    by_id = {s["id"]: s for s in body["sources"]}
    assert set(by_id) == {"openstax-finance", "gitlab-handbook", "not-yet-ingested"}

    assert by_id["openstax-finance"]["chunks"] == 2
    assert by_id["openstax-finance"]["files"] == 1
    assert by_id["openstax-finance"]["is_ingested"] is True
    assert by_id["openstax-finance"]["license"] == "CC BY 4.0"
    assert by_id["openstax-finance"]["domains"] == ["finance"]
    assert by_id["openstax-finance"]["last_fetched_at"] is not None

    assert by_id["gitlab-handbook"]["chunks"] == 1
    assert by_id["gitlab-handbook"]["domains"] == ["operations", "hr"]

    # A declared-but-not-yet-ingested source is still listed with zeros.
    assert by_id["not-yet-ingested"]["is_ingested"] is False
    assert by_id["not-yet-ingested"]["chunks"] == 0
    assert by_id["not-yet-ingested"]["last_fetched_at"] is None


def test_peek_returns_chunks_for_known_source(
    client: TestClient, fake_store, stub_manifest
) -> None:
    r = client.get("/knowledge/external/openstax-finance/peek?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["source_id"] == "openstax-finance"
    assert len(body["chunks"]) == 2
    for chunk in body["chunks"]:
        assert chunk["domain"] == "finance"
        assert chunk["filename"] == "openstax-finance.pdf"
        assert isinstance(chunk["text"], str)


def test_peek_unknown_source_returns_404(
    client: TestClient, fake_store, stub_manifest
) -> None:
    r = client.get("/knowledge/external/no-such-source/peek")
    assert r.status_code == 404


def test_peek_rejects_invalid_source_id_format(
    client: TestClient, fake_store, stub_manifest
) -> None:
    # Path validation should reject anything outside [a-zA-Z0-9_-]
    r = client.get("/knowledge/external/..%2Fetc%2Fpasswd/peek")
    assert r.status_code in (400, 404)


def test_peek_caps_limit_to_safe_max(
    client: TestClient, fake_store, stub_manifest
) -> None:
    r = client.get("/knowledge/external/openstax-finance/peek?limit=9999")
    assert r.status_code == 200
    # Only 2 chunks exist in the fake store; limit is capped to 25 internally.
    assert len(r.json()["chunks"]) == 2
