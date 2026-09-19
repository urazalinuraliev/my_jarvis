"""Cached read-through registry for departments.

The Executive's prompt-block builder (Phase 2) and the authority gate
(Phase 4) call into this on every turn — caching trades a small staleness
window for many DB round-trips per session.

Cache TTL is 60s. Calls to ``invalidate()`` clear it immediately and are
made by the route layer after any mutation, so the principal never sees
their own edits go missing for up to a minute.
"""
from __future__ import annotations

import threading
import time

from openexecutive.departments import store
from openexecutive.departments.models import DepartmentConfig, DepartmentState

_TTL_SECONDS = 60.0
_lock = threading.Lock()
_cache: list[DepartmentState] | None = None
_cache_expires_at: float = 0.0


def _refresh() -> list[DepartmentState]:
    global _cache, _cache_expires_at
    states = store.list_departments()
    _cache = states
    _cache_expires_at = time.monotonic() + _TTL_SECONDS
    return states


def list_states(*, force_refresh: bool = False) -> list[DepartmentState]:
    """Return all departments, served from the 60s cache when possible."""
    with _lock:
        if force_refresh or _cache is None or time.monotonic() >= _cache_expires_at:
            return _refresh()
        return list(_cache)


def get_state(slug: str) -> DepartmentState | None:
    for state in list_states():
        if state.config.slug == slug:
            return state
    return None


def list_configs() -> list[DepartmentConfig]:
    return [s.config for s in list_states()]


def slug_for_specialist(specialist_key: str) -> str | None:
    """Map a specialist agent key (e.g. ``cfo``) to its department slug."""
    for config in list_configs():
        if config.specialist_key == specialist_key:
            return config.slug
    return None


def specialist_for_slug(slug: str) -> str | None:
    """Map a department slug (e.g. ``finance``) to its specialist agent key."""
    state = get_state(slug)
    return state.config.specialist_key if state else None


def invalidate() -> None:
    """Drop the cache so the next read goes back to the store."""
    global _cache, _cache_expires_at
    with _lock:
        _cache = None
        _cache_expires_at = 0.0
