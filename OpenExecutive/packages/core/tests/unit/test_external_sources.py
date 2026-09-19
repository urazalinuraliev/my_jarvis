"""Unit tests for the OER manifest loader and file filtering."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openexecutive.knowledge import external_sources as oer
from openexecutive.knowledge.external_sources import (
    SOURCES_MANIFEST,
    Source,
    _domain_for_file,
    _iter_text_files,
    _make_chunk_id,
    ingest_source,
    load_manifest,
)


class _FakeStore:
    """In-memory stand-in for ChromaDBStore — captures rows for assertion."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.deleted_where: list[dict[str, Any]] = []

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str,
    ) -> None:
        for t, m, i in zip(texts, metadatas, ids, strict=True):
            self.rows.append({"text": t, "metadata": m, "id": i, "collection": collection})

    def delete_documents(self, collection: str, where: dict[str, Any]) -> None:
        self.deleted_where.append(where)


def test_manifest_parses_and_is_non_empty() -> None:
    sources = load_manifest()
    assert sources, "sources.yaml should declare at least one source"
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids)), "source ids must be unique"


def test_manifest_entries_are_well_formed() -> None:
    valid_domains = {
        "strategy", "finance", "hr", "legal",
        "operations", "marketing", "board", "product", "general",
    }
    valid_types = {"pdf", "html", "git", "openstax"}

    for src in load_manifest():
        assert src.id, f"missing id in {src}"
        assert src.url.startswith(("http://", "https://")), f"bad url for {src.id}"
        assert src.license, f"missing license for {src.id}"
        assert src.phase in (1, 2), f"bad phase for {src.id}"
        assert src.type in valid_types, f"bad type for {src.id}"
        assert src.domains, f"no domains for {src.id}"
        for d in src.domains:
            assert d in valid_domains, f"unknown domain {d!r} in {src.id}"


def test_manifest_ships_openstax_and_git_sources() -> None:
    types_in_manifest = {s.type for s in load_manifest()}
    assert "openstax" in types_in_manifest
    assert "git" in types_in_manifest


def test_openstax_sources_declare_slug() -> None:
    for src in load_manifest():
        if src.type == "openstax":
            assert src.slug, f"openstax source {src.id!r} must declare a slug"


def test_manifest_file_matches_module_constant() -> None:
    assert SOURCES_MANIFEST.exists()
    assert SOURCES_MANIFEST.name == "sources.yaml"


def test_chunk_id_is_deterministic() -> None:
    a = _make_chunk_id("src", "path/file.md", 3, "finance")
    b = _make_chunk_id("src", "path/file.md", 3, "finance")
    c = _make_chunk_id("src", "path/file.md", 4, "finance")
    assert a == b
    assert a != c


def test_chunk_id_disambiguates_domain_for_multi_domain_sources() -> None:
    """Multi-domain fan-out depends on chunk_id being distinct per domain."""
    fin = _make_chunk_id("src", "book.pdf", 0, "finance")
    mkt = _make_chunk_id("src", "book.pdf", 0, "marketing")
    assert fin != mkt


def _git_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **overrides: object,
) -> Source:
    monkeypatch.setattr(oer, "EXTERNAL_CACHE_DIR", tmp_path)
    defaults: dict[str, object] = {
        "id": "fixture",
        "title": "fixture",
        "publisher": "fixture",
        "license": "MIT",
        "phase": 2,
        "domains": ["operations"],
        "type": "git",
        "url": "https://example.invalid/repo.git",
    }
    defaults.update(overrides)
    return Source(**defaults)  # type: ignore[arg-type]


def test_iter_text_files_for_git_respects_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _git_source(
        tmp_path,
        monkeypatch,
        include_globs=["content/handbook/finance/**/*.md"],
    )
    repo = src.cache_dir
    (repo / "content" / "handbook" / "finance").mkdir(parents=True)
    (repo / "content" / "handbook" / "finance" / "fp_and_a.md").write_text("hello")
    (repo / "content" / "handbook" / "engineering").mkdir(parents=True)
    (repo / "content" / "handbook" / "engineering" / "design-docs.md").write_text("nope")
    (repo / "README.md").write_text("nope")

    files = _iter_text_files(src)
    rels = {str(p.relative_to(repo)) for p in files}
    assert rels == {"content/handbook/finance/fp_and_a.md"}


def test_domain_overrides_route_files_to_right_specialist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _git_source(
        tmp_path,
        monkeypatch,
        domain_overrides={
            "content/handbook/finance/": "finance",
            "content/handbook/engineering/": "operations",
        },
    )
    repo = src.cache_dir
    fin = repo / "content" / "handbook" / "finance" / "p.md"
    eng = repo / "content" / "handbook" / "engineering" / "p.md"
    fin.parent.mkdir(parents=True)
    eng.parent.mkdir(parents=True)
    fin.write_text("x")
    eng.write_text("x")

    assert _domain_for_file(src, fin) == "finance"
    assert _domain_for_file(src, eng) == "operations"


def _write_pdf_text(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Bypass real PDF parsing — return canned text for any path."""
    monkeypatch.setattr(oer, "_extract_text", lambda _p: text)


def test_multi_domain_pdf_fans_out_to_every_declared_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oer, "EXTERNAL_CACHE_DIR", tmp_path)
    src = Source(
        id="multi-pdf",
        title="Multi-Domain Book",
        publisher="t",
        license="CC BY 4.0",
        phase=1,
        domains=["strategy", "finance", "marketing"],
        type="pdf",
        url="https://example.invalid/book.pdf",
    )
    pdf = src.cache_dir / f"{src.id}.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")  # presence check; _extract_text is stubbed
    _write_pdf_text(monkeypatch, "alpha " * 600)  # ~2 chunks at 512 words

    store = _FakeStore()
    stats = ingest_source(src, store)  # type: ignore[arg-type]

    # Each declared domain gets its own copy of every chunk
    written_domains = {r["metadata"]["domain"] for r in store.rows}
    assert written_domains == {"strategy", "finance", "marketing"}
    chunks_per_domain = {d: sum(1 for r in store.rows if r["metadata"]["domain"] == d)
                        for d in written_domains}
    assert len(set(chunks_per_domain.values())) == 1, "same chunk count per domain"
    # Chunk ids must disambiguate domains so upsert doesn't collapse copies
    assert len({r["id"] for r in store.rows}) == len(store.rows)
    # files = 1 physical file, chunks = total rows written across all domains
    assert stats.files == 1
    assert stats.chunks == len(store.rows)


def test_git_source_with_domain_overrides_does_not_fan_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oer, "EXTERNAL_CACHE_DIR", tmp_path)
    src = Source(
        id="git-routed",
        title="Routed Handbook",
        publisher="t",
        license="MIT",
        phase=2,
        domains=["operations", "hr", "finance"],
        type="git",
        url="https://example.invalid/handbook.git",
        include_globs=["content/**/*.md"],
        domain_overrides={
            "content/finance/": "finance",
            "content/people/": "hr",
        },
    )
    repo = src.cache_dir
    (repo / "content" / "finance").mkdir(parents=True)
    (repo / "content" / "people").mkdir(parents=True)
    (repo / "content" / "finance" / "fp.md").write_text("finance content " * 50)
    (repo / "content" / "people" / "hire.md").write_text("hiring content " * 50)

    store = _FakeStore()
    ingest_source(src, store)  # type: ignore[arg-type]

    domains_for = {
        r["metadata"]["filename"]: r["metadata"]["domain"] for r in store.rows
    }
    assert domains_for == {"fp.md": "finance", "hire.md": "hr"}


def test_iter_text_files_for_pdf_returns_single_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oer, "EXTERNAL_CACHE_DIR", tmp_path)
    src = Source(
        id="pdf-fixture",
        title="t",
        publisher="t",
        license="CC BY 4.0",
        phase=1,
        domains=["finance"],
        type="pdf",
        url="https://example.invalid/book.pdf",
    )
    expected = src.cache_dir / f"{src.id}.pdf"
    assert _iter_text_files(src) == [expected]
