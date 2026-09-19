from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Error-message signatures of a corrupt store. Deliberately specific: a Rust
# panic as such is NOT one (see is_rust_panic) — e.g. an on-disk format this
# chromadb version can't read would panic too, and moving that store aside
# would hide good data behind an empty one.
_CORRUPTION_MARKERS: tuple[str, ...] = (
    # pyo3 panic from a corrupt HNSW index / chroma.sqlite3:
    # "range start index N out of range for slice of length M"
    "out of range for slice",
    "range start index",
    # SQLite
    "file is not a database",
    "database disk image is malformed",
    "database is corrupt",
    # hnswlib: "Index seems to be corrupted or unsupported"
    "corrupted",
)


# See ChromaDBStore._open_client.
_OPEN_LOCK = threading.Lock()


def is_rust_panic(exc: BaseException) -> bool:
    """True for ``pyo3_runtime.PanicException`` from chromadb's Rust bindings.

    It derives from BaseException, so ``except Exception`` does not catch it.
    """
    return type(exc).__name__ == "PanicException"


def _is_corruption(exc: BaseException) -> bool:
    """Return True when *exc* carries a storage-corruption signature.

    Everything else — a locked file, a second client with different settings,
    permissions, a full disk, an unrecognised panic — is NOT corruption:
    moving the store aside would not fix it and would hide the operator's
    data behind a fresh empty store.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _CORRUPTION_MARKERS)


def _move_corrupt_store(persist_directory: str | Path) -> Path:
    """Rename a corrupt ChromaDB directory aside so a fresh store can be created.

    ``os.rename`` within the same parent is atomic: it either moves the whole
    directory or fails leaving it untouched. (``shutil.move`` would fall back
    to copy-then-delete, which on Windows deletes every closable file of the
    live store before failing on a locked one.) Raises ``OSError`` on failure.
    """
    path = Path(persist_directory)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    # If a stale backup already exists for this second, append a counter.
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
        n += 1
    os.rename(path, backup)
    return backup


def _cached_chroma_systems(persist_directory: str | Path) -> dict[str, Any]:
    """chromadb's cached System objects for *persist_directory*, by cache key."""
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
    except ImportError:
        return {}
    target = Path(persist_directory).resolve()
    found = {}
    for key, system in list(SharedSystemClient._identifier_to_system.items()):
        try:
            if Path(key).resolve() == target:
                found[key] = system
        except (OSError, ValueError):
            continue
    return found


def _discard_failed_chroma_systems(
    persist_directory: str | Path, cached_before: dict[str, Any]
) -> None:
    """Stop and uncache the System a failed ``PersistentClient`` call left behind.

    chromadb caches one System per path and registers it *before* starting
    it, so a failed start leaves a half-started System (possibly still holding
    files open) that every later client for the same path would reuse — the
    store could then never be reopened in-process. Only entries that did not
    exist before the failed call are touched, so a working client for the
    same path elsewhere in the process keeps its System.
    """
    from chromadb.api.shared_system_client import SharedSystemClient

    for key, system in _cached_chroma_systems(persist_directory).items():
        if key in cached_before:
            continue
        SharedSystemClient._identifier_to_system.pop(key, None)
        try:
            system.stop()
        except Exception:
            logger.debug("ChromaDB: stopping a failed System raised", exc_info=True)


class KnowledgeStore(ABC):
    @abstractmethod
    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str,
    ) -> None: ...

    @abstractmethod
    def query(
        self,
        query_text: str,
        collection: str,
        domain_filter: list[str] | None = None,
        n_results: int = 5,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def collection_exists(self, collection: str) -> bool: ...

    @abstractmethod
    def get_collection_count(self, collection: str) -> int: ...

    @abstractmethod
    def delete_documents(self, collection: str, where: dict[str, Any]) -> None: ...


class ChromaDBStore(KnowledgeStore):
    BUILTIN_COLLECTION = "builtin_knowledge"
    COMPANY_COLLECTION = "company_docs"
    FAILURES_COLLECTION = "failure_cases"
    # Web-research artifacts persisted from executive_research runs. Kept
    # SEPARATE from COMPANY_COLLECTION so unvetted, machine-generated
    # research never blends into curated company knowledge — it is
    # retrieved under its own clearly-labelled, lower-ranked section.
    RESEARCH_COLLECTION = "recent_research"
    # Synced Notion wiki pages. Kept SEPARATE from COMPANY_COLLECTION
    # because a Notion share is multi-writer and unreviewed — anyone
    # who can edit a shared page can inject text the agents will read.
    # Retrieved under its own clearly-labelled, lower-ranked section.
    NOTION_COLLECTION = "notion_wiki"

    def __init__(self, persist_directory: str | Path = "./chroma_db") -> None:
        path = str(persist_directory)
        # ``BaseException``: a pyo3 PanicException derives from it, so
        # ``except Exception`` would let a corruption panic crash startup.
        try:
            self._client = self._open_client(path)
            return
        except BaseException as exc:
            if not _is_corruption(exc):
                if is_rust_panic(exc):
                    # Unrecognised panic: leave the store where it is, but
                    # surface it as an Exception so callers' degraded-mode
                    # handlers (``except Exception``) can catch it.
                    raise RuntimeError(
                        f"ChromaDB panicked opening {path}: {exc}"
                    ) from exc
                raise
            logger.warning(
                "ChromaDB: store at %s looks corrupt (%s: %s); moving it aside "
                "and starting fresh",
                path,
                type(exc).__name__,
                exc,
            )

        backup = _move_corrupt_store(path)
        logger.warning("ChromaDB: moved corrupt store %s → %s", path, backup)
        try:
            self._client = self._open_client(path)
        except BaseException as exc:
            if not is_rust_panic(exc):
                raise
            raise RuntimeError(
                f"ChromaDB still failing at {path} after moving the corrupt "
                f"store to {backup}: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _open_client(path: str) -> Any:
        """``PersistentClient`` that never leaves a broken System in chromadb's cache.

        Serialized per process: retrieval opens stores from worker threads, and
        a concurrent open could otherwise pick up (then discard) the System
        another thread is still starting.
        """
        import chromadb
        from chromadb.config import Settings

        with _OPEN_LOCK:
            cached_before = _cached_chroma_systems(path)
            try:
                return chromadb.PersistentClient(
                    path=path, settings=Settings(anonymized_telemetry=False)
                )
            except BaseException:
                _discard_failed_chroma_systems(path, cached_before)
                raise

    def _get_or_create_collection(self, name: str) -> Any:
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection: str = BUILTIN_COLLECTION,
    ) -> None:
        col = self._get_or_create_collection(collection)
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            col.upsert(
                documents=texts[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size],
            )

    def query(
        self,
        query_text: str,
        collection: str = BUILTIN_COLLECTION,
        domain_filter: list[str] | None = None,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        col = self._get_or_create_collection(collection)

        count = col.count()
        if count == 0:
            return []

        where: dict[str, Any] | None = None
        if domain_filter:
            if len(domain_filter) == 1:
                where = {"domain": domain_filter[0]}
            else:
                where = {"domain": {"$in": domain_filter}}

        query_kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": min(n_results, count),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_kwargs["where"] = where

        results = col.query(**query_kwargs)

        output = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                strict=False,
            ):
                output.append({"text": doc, "metadata": meta, "distance": dist})
        return output

    def collection_exists(self, collection: str) -> bool:
        try:
            self._client.get_collection(collection)
            return True
        except Exception:
            return False

    def get_collection_count(self, collection: str) -> int:
        try:
            col = self._client.get_collection(collection)
            return col.count()
        except Exception:
            return 0

    def delete_documents(self, collection: str, where: dict[str, Any]) -> None:
        try:
            col = self._get_or_create_collection(collection)
            col.delete(where=where)
        except Exception:
            pass

    def delete_company_docs(self) -> None:
        """Delete and recreate the company_docs collection, clearing all indexed documents."""
        import contextlib

        with contextlib.suppress(Exception):
            self._client.delete_collection(self.COMPANY_COLLECTION)
        # Recreate with the same HNSW settings so subsequent upserts work normally.
        self._get_or_create_collection(self.COMPANY_COLLECTION)

    def delete_notion_docs(self) -> None:
        """Drop synced Notion chunks from the isolated collection and any
        leftover COMPANY rows tagged ``type=notion`` (pre-isolation ingest)."""
        self.delete_documents(collection=self.NOTION_COLLECTION, where={"type": "notion"})
        self.delete_documents(collection=self.COMPANY_COLLECTION, where={"type": "notion"})
