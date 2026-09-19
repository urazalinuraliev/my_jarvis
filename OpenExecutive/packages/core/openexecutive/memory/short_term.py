from __future__ import annotations

from typing import Any


class ConversationHistory:
    """Manages in-context conversation history with token-aware trimming."""

    def __init__(self, max_turns: int = 20) -> None:
        self.max_turns = max_turns
        self._messages: list[dict[str, Any]] = []

    def add_user(self, content: str | list[dict[str, Any]]) -> None:
        self._messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str | list[dict[str, Any]]) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def _trim(self) -> None:
        max_messages = self.max_turns * 2
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
