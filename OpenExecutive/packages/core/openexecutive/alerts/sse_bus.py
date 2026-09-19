from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# In-process fan-out. Each connected SSE client owns one queue; publishers
# enqueue on every queue. Single-process only — multi-process deploys would
# need Redis pub/sub here.
_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    _subscribers.discard(q)


def publish(event: dict[str, Any]) -> None:
    """Non-blocking publish. Drops events for slow consumers rather than blocking."""
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("sse_bus: subscriber queue full — dropping event")


def subscriber_count() -> int:
    return len(_subscribers)
