"""External source adapters.

Each adapter implements the ``Source`` protocol in ``base.py``. The
pipeline instantiates one per ``signal_type`` it knows about. v1 ships
``vendor_status``; PR-B adds ``rss`` and ``stock``.

Source-of-truth for which adapter handles which watchlist row is the
``signal_type`` column on the watchlist row. The pipeline uses
``get_source_for_kind()`` to look up the implementation.
"""
from __future__ import annotations

from openexecutive.monitoring.sources.base import Signal, Source
from openexecutive.monitoring.sources.edgar import EdgarSource
from openexecutive.monitoring.sources.page_watch import PageWatchSource
from openexecutive.monitoring.sources.query import QuerySource
from openexecutive.monitoring.sources.rss import RssSource
from openexecutive.monitoring.sources.stock import StockSource
from openexecutive.monitoring.sources.vendor_status import VendorStatusSource

# Registry of installed adapters, keyed by signal_type. New adapters
# register themselves here so the pipeline can dispatch via dict lookup.
_REGISTRY: dict[str, Source] = {
    VendorStatusSource.kind: VendorStatusSource(),
    RssSource.kind: RssSource(),
    StockSource.kind: StockSource(),
    QuerySource.kind: QuerySource(),
    EdgarSource.kind: EdgarSource(),
    PageWatchSource.kind: PageWatchSource(),
}


def get_source_for_kind(signal_type: str) -> Source | None:
    """Return the adapter for a signal_type, or None if unregistered."""
    return _REGISTRY.get(signal_type)


def list_registered_kinds() -> list[str]:
    """Snapshot of every signal_type with an installed adapter."""
    return sorted(_REGISTRY.keys())


__all__ = ["Signal", "Source", "get_source_for_kind", "list_registered_kinds"]
