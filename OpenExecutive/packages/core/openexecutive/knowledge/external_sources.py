"""Download and ingest open-licensed OER textbooks and handbooks.

Sources are declared in ``knowledge/sources.yaml``. Each source resolves to a
local cache under ``knowledge/external/<id>/`` and is indexed into the
``builtin_knowledge`` ChromaDB collection so the standard retriever picks it
up alongside the hand-written notes.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from openexecutive.knowledge.loader import (
    chunk_text,
    extract_text_from_pdf,
)
from openexecutive.knowledge.store import ChromaDBStore

SOURCES_MANIFEST = Path(__file__).parent / "sources.yaml"
EXTERNAL_CACHE_DIR = Path(__file__).parent / "external"

# Anything older than this is fine to re-fetch even without --force.
DEFAULT_TIMEOUT_S = 300.0

# Some OER CDNs (assets.openstax.org) reject default httpx UA. Identify
# ourselves with a real-looking browser string.
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
}


@dataclass
class Source:
    id: str
    title: str
    publisher: str
    license: str
    phase: int
    domains: list[str]
    type: str
    url: str
    slug: str | None = None
    include_globs: list[str] = field(default_factory=list)
    domain_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def cache_dir(self) -> Path:
        return EXTERNAL_CACHE_DIR / self.id

    @property
    def primary_domain(self) -> str:
        return self.domains[0] if self.domains else "general"


def load_manifest(path: Path = SOURCES_MANIFEST) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Source(**entry) for entry in raw.get("sources", [])]


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


async def _download_http(url: str, dest: Path, *, force: bool) -> Path:
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    async with (
        httpx.AsyncClient(
            follow_redirects=True,
            timeout=DEFAULT_TIMEOUT_S,
            headers=_HTTP_HEADERS,
        ) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        with tmp.open("wb") as f:
            async for chunk in response.aiter_bytes(chunk_size=1 << 16):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def _git_clone_or_pull(url: str, dest: Path, *, force: bool) -> Path:
    """Shallow clone or fast-forward an existing checkout."""
    if dest.exists() and force:
        shutil.rmtree(dest)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", url, str(dest)],
            check=True,
        )
    else:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "origin"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", "FETCH_HEAD"],
            check=True,
        )
    return dest


async def _resolve_openstax_pdf_url(slug: str) -> str:
    """Look up the current high-resolution PDF URL for an OpenStax book by slug."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=30.0, headers=_HTTP_HEADERS
    ) as client:
        index = await client.get(
            "https://openstax.org/apps/cms/api/v2/pages/",
            params={"type": "books.Book", "slug": slug, "format": "json"},
        )
        index.raise_for_status()
        items = index.json().get("items") or []
        if not items:
            raise ValueError(f"OpenStax slug {slug!r} not found")
        page_id = items[0]["id"]
        detail = await client.get(
            f"https://openstax.org/apps/cms/api/v2/pages/{page_id}/",
            params={"format": "json"},
        )
        detail.raise_for_status()
        pdf_url = detail.json().get("high_resolution_pdf_url")
        if not pdf_url:
            raise ValueError(f"No PDF URL for OpenStax slug {slug!r}")
        return pdf_url


async def fetch_source(source: Source, *, force: bool = False) -> Path:
    if source.type == "pdf":
        target = source.cache_dir / f"{source.id}.pdf"
        return await _download_http(source.url, target, force=force)
    if source.type == "openstax":
        if not source.slug:
            raise ValueError(f"openstax source {source.id!r} is missing 'slug'")
        target = source.cache_dir / f"{source.id}.pdf"
        if target.exists() and not force:
            return target
        pdf_url = await _resolve_openstax_pdf_url(source.slug)
        return await _download_http(pdf_url, target, force=force)
    if source.type == "html":
        target = source.cache_dir / f"{source.id}.html"
        return await _download_http(source.url, target, force=force)
    if source.type == "git":
        return await asyncio.to_thread(
            _git_clone_or_pull, source.url, source.cache_dir, force=force
        )
    raise ValueError(f"unsupported source type: {source.type}")


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def _iter_text_files(source: Source) -> list[Path]:
    if source.type in ("pdf", "openstax"):
        return [source.cache_dir / f"{source.id}.pdf"]
    if source.type == "html":
        return [source.cache_dir / f"{source.id}.html"]

    # git: walk the checkout and apply include_globs (relative to checkout root)
    root = source.cache_dir
    matches: set[Path] = set()
    if not source.include_globs:
        matches.update(root.rglob("*.md"))
    else:
        for pat in source.include_globs:
            matches.update(p for p in root.glob(pat) if p.is_file())
    return sorted(matches)


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix in (".md", ".markdown", ".txt", ".rst"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".mdx":
        import re
        text = path.read_text(encoding="utf-8", errors="replace")
        # Strip import/export statements and JSX tags so only prose remains.
        text = re.sub(r"^(import|export)\s.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"<[A-Z][^>]*>[\s\S]*?</[A-Z][^>]*>", " ", text)
        text = re.sub(r"<[A-Z][^>]*/?>", " ", text)
        return text
    if suffix in (".html", ".htm"):
        text = path.read_text(encoding="utf-8", errors="replace")
        # Lightweight tag strip — adequate for OER pages which are mostly text.
        import re

        text = re.sub(r"<script[\s\S]*?</script>", " ", text)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        return text
    return ""


def _domain_for_file(source: Source, path: Path) -> str:
    if source.type != "git" or not source.domain_overrides:
        return source.primary_domain
    rel = str(path.relative_to(source.cache_dir))
    for prefix, domain in source.domain_overrides.items():
        if rel.startswith(prefix):
            return domain
    return source.primary_domain


def _make_chunk_id(source_id: str, file_path: str, chunk_index: int, domain: str = "") -> str:
    base = f"oer::{source_id}::{file_path}::{chunk_index}::{domain}"
    return hashlib.md5(base.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@dataclass
class IngestStats:
    source_id: str
    files: int = 0
    chunks: int = 0
    skipped: bool = False
    error: str | None = None


def ingest_source(
    source: Source,
    store: ChromaDBStore,
    *,
    collection: str = ChromaDBStore.BUILTIN_COLLECTION,
    purge_existing: bool = True,
) -> IngestStats:
    """Chunk + index every file in the source's local cache.

    Idempotent: deterministic chunk ids upsert in place. ``purge_existing``
    additionally removes prior chunks for this source_id so a shrunken corpus
    doesn't leave orphans behind.
    """
    stats = IngestStats(source_id=source.id)

    if purge_existing:
        store.delete_documents(collection, where={"source_id": source.id})

    files = _iter_text_files(source)
    if not files:
        stats.skipped = True
        return stats

    for path in files:
        text = _extract_text(path)
        if not text.strip():
            continue
        chunks = chunk_text(text)
        if not chunks:
            continue
        rel_path = (
            str(path.relative_to(source.cache_dir)) if source.type == "git" else path.name
        )
        # Decide which domains this file's chunks should be tagged under.
        # git + domain_overrides => per-path single-domain routing
        # otherwise              => fan out a copy per declared domain
        target_domains = (
            [_domain_for_file(source, path)]
            if (source.type == "git" and source.domain_overrides)
            else (source.domains or ["general"])
        )
        stats.files += 1
        for domain in target_domains:
            metadatas: list[dict[str, Any]] = [
                {
                    "domain": domain,
                    "filename": path.name,
                    "source": str(path),
                    "source_id": source.id,
                    "source_url": source.url,
                    "license": source.license,
                    "publisher": source.publisher,
                    "title": source.title,
                    "chunk_index": i,
                    "type": "external",
                }
                for i in range(len(chunks))
            ]
            ids = [
                _make_chunk_id(source.id, rel_path, i, domain) for i in range(len(chunks))
            ]
            store.add_documents(
                texts=chunks, metadatas=metadatas, ids=ids, collection=collection
            )
            stats.chunks += len(chunks)

    return stats


async def ingest_all(
    *,
    phases: list[int] | None = None,
    source_ids: list[str] | None = None,
    force: bool = False,
    store: ChromaDBStore | None = None,
    progress: Any | None = None,
) -> list[IngestStats]:
    """Download every selected source, then chunk and index it.

    ``progress`` may be any object with ``log(msg: str)`` (e.g. a rich Console).
    """

    def _log(msg: str) -> None:
        if progress is not None:
            progress.log(msg)

    if store is None:
        from openexecutive.config import get_settings

        settings = get_settings()
        store = ChromaDBStore(persist_directory=settings.vector_store_path)

    selected: list[Source] = []
    for src in load_manifest():
        if phases and src.phase not in phases:
            continue
        if source_ids and src.id not in source_ids:
            continue
        selected.append(src)

    results: list[IngestStats] = []
    for src in selected:
        _log(f"[bold]{src.id}[/bold] — {src.title} ({src.license})")
        try:
            await fetch_source(src, force=force)
        except Exception as exc:
            results.append(IngestStats(source_id=src.id, error=f"fetch failed: {exc}"))
            _log(f"  [red]fetch failed:[/red] {exc}")
            continue
        try:
            stats = await asyncio.to_thread(ingest_source, src, store)
        except Exception as exc:
            results.append(IngestStats(source_id=src.id, error=f"ingest failed: {exc}"))
            _log(f"  [red]ingest failed:[/red] {exc}")
            continue
        results.append(stats)
        if stats.skipped:
            _log("  [yellow]no matching files[/yellow]")
        else:
            _log(f"  indexed [green]{stats.chunks}[/green] chunks from {stats.files} files")
    return results
