"""Cached read-through registry for People.

Pattern mirrors `departments.registry`: 60s TTL, thread-safe, invalidated
by the route layer after any mutation.
"""
from __future__ import annotations

import threading
import time

from openexecutive.people import store
from openexecutive.people.models import Person

_TTL_SECONDS = 60.0
_lock = threading.Lock()
_cache: list[Person] | None = None
_cache_expires_at: float = 0.0


def _refresh() -> list[Person]:
    global _cache, _cache_expires_at
    people = store.list_people()
    _cache = people
    _cache_expires_at = time.monotonic() + _TTL_SECONDS
    return people


def list_people(*, force_refresh: bool = False) -> list[Person]:
    """Return all non-archived people, served from the 60s cache."""
    with _lock:
        if force_refresh or _cache is None or time.monotonic() >= _cache_expires_at:
            return _refresh()
        return list(_cache)


def get_person(person_id: int) -> Person | None:
    for p in list_people():
        if p.id == person_id:
            return p
    return None


def get_principal() -> Person | None:
    for p in list_people():
        if p.is_principal:
            return p
    return None


def invalidate() -> None:
    """Drop the cache so the next read goes back to the store."""
    global _cache, _cache_expires_at
    with _lock:
        _cache = None
        _cache_expires_at = 0.0
