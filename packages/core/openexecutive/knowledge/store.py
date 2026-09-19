from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _is_corruption(exc: BaseException) -> bool:
    """Return True when *exc* is a ChromaDB storage-corruption signal.

    ChromaDB's Rust bindings (pyo3) raise ``pyo3_runtime.PanicException``
    with messages like "range start index N out of range for slice of length M"
    when the on-disk HNSW index or ``chroma.sqlite3`` is corrupted. SQLite
    itself raises ``sqlite3.DatabaseError`` / ``DatabaseError: file is not a
    database`` for the same class of problem. We treat all of these as
    corruption so the caller can wipe and re-initialise.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "panicexception",
            "pyo3",
            "out of range for slice",
            "range start index",
            "file is not a database",
            "database disk image is malformed",
            "corrupted",
            "database is corrupt",
        )
    )


def _recover_chroma_path(persist_directory: str | Path) -> Path:
    """Back up a corrupt ChromaDB directory and return a fresh path.

    Called when PersistentClient initialization fails with a corruption
    signal. Moves the bad directory aside (so the operator can inspect it)
    and returns the *original* path — the next PersistentClient call will
    create a fresh empty store there.
    """
    path = Path(persist_directory)
    if not path.exists():
        return path
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    # If a stale backup already exists for this second, append a counter.
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
        n += 1
    try:
        shutil.move(str(path), str(backup))
        logger.warning(
            "ChromaDB: moved corrupt store %s → %s; starting fresh",
            path,
            backup,
        )
    except Exception:
        # If the move fails (e.g. permissions), fall back to a wipe so we
        # don't loop forever on the same bad path.
        logger.exception(
            "ChromaDB: could not back up corrupt store %s; wiping in place", path
        )
        try:
            shutil.rmtree(str(path), ignore_errors=True)
        except Exception:
            logger.exception("ChromaDB: rmtree of %s also failed", path)
    return path


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
        import chromadb
        from chromadb.config import Settings

        path = str(persist_directory)
        # ChromaDB's Rust bindings (pyo3) can raise
        # ``pyo3_runtime.PanicException: range start index N out of range for
        # slice of length M`` when the on-disk HNSW index or chroma.sqlite3
        # is corrupted. SQLite itself raises ``DatabaseError: file is not a
        # database`` for the same class of problem.
        #
        # We do NOT rely solely on string-matching the exception message to
        # decide whether to recover: Rust panics can surface as exception
        # types whose text we don't predict, and a missed match would let
        # the panic crash startup. Instead, ANY exception on attempt 0 is
        # treated as a potential storage failure — back up the directory,
        # wipe it, and retry once. A second failure propagates so the
        # lifespan's degradation handler can log + continue without RAG.
        for attempt in range(2):
            try:
                self._client = chromadb.PersistentClient(
                    path=path,
                    settings=Settings(anonymized_telemetry=False),
                )
                return
            except Exception as exc:
                if attempt == 0:
                    # Broad catch: any failure on first init is treated as a
                    # storage problem. Back up the bad directory (so the
                    # operator can inspect it) and retry with a fresh store.
                    if _is_corruption(exc):
                        logger.warning(
                            "ChromaDB: corruption detected at %s (%s: %s); "
                            "backing up and re-initialising",
                            path,
                            type(exc).__name__,
                            exc,
                        )
                    else:
                        logger.warning(
                            "ChromaDB: PersistentClient failed at %s (%s: %s); "
                            "backing up directory and re-initialising",
                            path,
                            type(exc).__name__,
                            exc,
                        )
                    _recover_chroma_path(path)
                    continue
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
