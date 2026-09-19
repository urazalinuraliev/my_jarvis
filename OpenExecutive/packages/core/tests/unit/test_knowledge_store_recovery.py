"""ChromaDBStore start-up recovery: only real corruption moves the store aside.

chromadb.PersistentClient is replaced with a scripted fake, so no real store
is opened; each test gets its own temp store directory.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import chromadb
import pytest

from openexecutive.knowledge import store as store_module
from openexecutive.knowledge.store import ChromaDBStore, _is_corruption


class PanicException(BaseException):
    """Stand-in for pyo3_runtime.PanicException, which derives from BaseException."""


class _ScriptedClient:
    """PersistentClient replacement that raises the scripted outcomes in order."""

    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def __call__(self, path: str, settings: Any) -> object:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if outcome is not None:
            raise outcome
        return object()


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    path = tmp_path / "chroma_db"
    path.mkdir()
    (path / "chroma.sqlite3").write_bytes(b"precious")
    return path


def _script(monkeypatch: pytest.MonkeyPatch, *outcomes: BaseException | None) -> _ScriptedClient:
    client = _ScriptedClient(list(outcomes))
    monkeypatch.setattr(chromadb, "PersistentClient", client)
    return client


def _backups(store_dir: Path) -> list[Path]:
    return sorted(store_dir.parent.glob(f"{store_dir.name}.corrupt-*"))


@pytest.mark.parametrize(
    "exc",
    [
        PanicException("range start index 12 out of range for slice of length 4"),
        sqlite3.DatabaseError("file is not a database"),
        sqlite3.DatabaseError("database disk image is malformed"),
        RuntimeError("Index seems to be corrupted or unsupported"),
    ],
)
def test_corruption_signals_are_recognised(exc: BaseException) -> None:
    assert _is_corruption(exc)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("An instance of Chroma already exists for ./chroma_db with different settings"),
        sqlite3.OperationalError("database is locked"),
        PermissionError("[WinError 32] The process cannot access the file"),
        KeyboardInterrupt(),
        # A panic without a corruption signature (e.g. an unreadable format).
        PanicException("called `Option::unwrap()` on a `None` value"),
    ],
)
def test_ordinary_failures_are_not_corruption(exc: BaseException) -> None:
    assert not _is_corruption(exc)


def test_non_corruption_error_leaves_the_store_in_place(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    client = _script(monkeypatch, ValueError("An instance of Chroma already exists with different settings"))
    with pytest.raises(ValueError):
        ChromaDBStore(persist_directory=store_dir)
    assert client.calls == 1
    assert (store_dir / "chroma.sqlite3").read_bytes() == b"precious"
    assert _backups(store_dir) == []


def test_corrupt_store_is_moved_aside_and_reopened(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    client = _script(monkeypatch, sqlite3.DatabaseError("file is not a database"), None)
    ChromaDBStore(persist_directory=store_dir)
    assert client.calls == 2
    backups = _backups(store_dir)
    assert len(backups) == 1
    assert (backups[0] / "chroma.sqlite3").read_bytes() == b"precious"


def test_rust_panic_is_recovered(monkeypatch: pytest.MonkeyPatch, store_dir: Path) -> None:
    _script(monkeypatch, PanicException("range start index 3 out of range for slice of length 1"), None)
    ChromaDBStore(persist_directory=store_dir)
    assert len(_backups(store_dir)) == 1


def test_failed_move_never_deletes_the_store(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    _script(monkeypatch, sqlite3.DatabaseError("file is not a database"), None)

    def refuse_rename(src: object, dst: object) -> None:
        raise PermissionError("file in use")

    # os.rename is all-or-nothing; shutil.move's copy+delete fallback is not.
    monkeypatch.setattr(store_module.os, "rename", refuse_rename)
    with pytest.raises(PermissionError):
        ChromaDBStore(persist_directory=store_dir)
    assert (store_dir / "chroma.sqlite3").read_bytes() == b"precious"


def test_repeated_panic_surfaces_as_an_exception(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    panic = PanicException("range start index 3 out of range for slice of length 1")
    _script(monkeypatch, panic, PanicException("range start index 9 out of range"))
    # RuntimeError (an Exception), so the lifespan's degraded-mode handler catches it.
    with pytest.raises(RuntimeError, match="still failing"):
        ChromaDBStore(persist_directory=store_dir)


def test_keyboard_interrupt_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    _script(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        ChromaDBStore(persist_directory=store_dir)
    assert _backups(store_dir) == []


def test_unrecognised_panic_leaves_the_store_and_is_catchable(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    _script(monkeypatch, PanicException("called `Option::unwrap()` on a `None` value"))
    with pytest.raises(RuntimeError, match="panicked"):
        ChromaDBStore(persist_directory=store_dir)
    assert (store_dir / "chroma.sqlite3").read_bytes() == b"precious"
    assert _backups(store_dir) == []


class _FakeSystem:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_failed_open_uncaches_only_its_own_system(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path, tmp_path: Path
) -> None:
    """chromadb registers a System before starting it; a failed start must not
    leave it cached (every later open of the path would reuse it), while a
    System some other working client registered earlier stays put."""
    from chromadb.api.shared_system_client import SharedSystemClient

    cache: dict[str, object] = {}
    monkeypatch.setattr(SharedSystemClient, "_identifier_to_system", cache)
    other = _FakeSystem()
    cache[str(tmp_path / "other_store")] = other
    failed = _FakeSystem()

    def failing_client(path: str, settings: Any) -> object:
        cache[path] = failed  # what chromadb does before System.start()
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(chromadb, "PersistentClient", failing_client)
    with pytest.raises(sqlite3.OperationalError):
        ChromaDBStore(persist_directory=store_dir)

    assert str(store_dir) not in cache
    assert failed.stopped
    assert cache == {str(tmp_path / "other_store"): other}
    assert not other.stopped


def test_failed_open_keeps_a_working_system_for_the_same_path(
    monkeypatch: pytest.MonkeyPatch, store_dir: Path
) -> None:
    from chromadb.api.shared_system_client import SharedSystemClient

    working = _FakeSystem()
    cache: dict[str, object] = {str(store_dir): working}
    monkeypatch.setattr(SharedSystemClient, "_identifier_to_system", cache)
    _script(monkeypatch, ValueError("An instance of Chroma already exists with different settings"))
    with pytest.raises(ValueError):
        ChromaDBStore(persist_directory=store_dir)
    assert cache == {str(store_dir): working}
    assert not working.stopped
