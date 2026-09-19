"""Pick a name that does not collide with an existing one.

Used for timestamped backups (a corrupt ChromaDB directory, a legacy SQLite
table) where two backups within the same second must not overwrite each other.
"""
from __future__ import annotations

from collections.abc import Callable


def first_unused(candidate: str, is_taken: Callable[[str], bool], separator: str) -> str:
    """Return *candidate*, else ``candidate{separator}1``, ``…2``, … — the first free one."""
    name = candidate
    n = 1
    while is_taken(name):
        name = f"{candidate}{separator}{n}"
        n += 1
    return name
