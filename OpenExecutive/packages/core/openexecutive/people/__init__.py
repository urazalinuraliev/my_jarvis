"""People package — real humans the Executive can address, assign, and wait on.

Phase 3 ships the model, store, registry, and channel helper.
The WaitForHuman workflow primitive and inbound resolver land in Phase 6.
"""
from __future__ import annotations

from openexecutive.people.models import (
    AuthorityScope,
    AvailabilityWindow,
    Person,
    PreferredChannel,
)
from openexecutive.people.registry import (
    get_person,
    get_principal,
    invalidate,
    list_people,
)

__all__ = [
    "AuthorityScope",
    "AvailabilityWindow",
    "Person",
    "PreferredChannel",
    "get_person",
    "get_principal",
    "invalidate",
    "list_people",
]
