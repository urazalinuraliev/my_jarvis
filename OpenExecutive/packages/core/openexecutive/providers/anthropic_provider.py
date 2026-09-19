from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from typing import Any

import anthropic


class AnthropicProvider:
    """Thin delegate over ``anthropic.AsyncAnthropic``.

    Holds one ``AsyncAnthropic`` for the lifetime of the process; the SDK
    is async-safe and pools its own httpx connections.
    """

    def __init__(self, *, api_key: str, timeout: float | None = None) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if timeout is not None:
            kwargs["timeout"] = timeout
        self._client = anthropic.AsyncAnthropic(**kwargs)

    def messages_create(self, **kwargs: Any) -> Awaitable[Any]:
        return self._client.messages.create(**kwargs)

    def messages_stream(self, **kwargs: Any) -> AbstractAsyncContextManager[Any]:
        return self._client.messages.stream(**kwargs)
