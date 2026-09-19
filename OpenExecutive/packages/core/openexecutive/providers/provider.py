from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every backend must satisfy.

    Both methods accept and return Anthropic-shape values so call sites do not
    need to know whether they are talking to Anthropic directly or to a
    translated backend (e.g. OpenRouter). All kwargs are the same kwargs
    ``anthropic.AsyncAnthropic().messages.create/stream`` accepts.
    """

    def messages_create(self, **kwargs: Any) -> Awaitable[Any]:
        """Non-streaming completion. Returns an ``anthropic.types.Message``-shaped object."""
        ...

    def messages_stream(self, **kwargs: Any) -> AbstractAsyncContextManager[Any]:
        """Streaming completion. Returns an async context manager.

        The yielded stream must support ``async for event in stream`` emitting
        Anthropic-shape stream events (``content_block_start``,
        ``content_block_delta``, ``content_block_stop``, ``message_delta``,
        ``message_stop``) and ``await stream.get_final_message()`` returning
        the fully assembled ``Message``.
        """
        ...
