"""Named client-company slots — multi-client support for fractional executives.

One Open Executive instance, several client companies, exactly one active at a
time. A *slot* is an on-disk save file of the full company context (profile,
docs, skills, MCP config, and the shared SQLite state); activating a slot saves
the current client back to its slot and restores the target. Single-company
installs never touch this module — slots only exist once explicitly created.
"""
from openexecutive.clients.slots import (
    ClientSlotConflictError,
    ClientSlotError,
    ClientSlotNotFoundError,
    activate_client_slot,
    create_client_slot,
    delete_client_slot,
    get_active_client,
    list_client_slots,
    save_active_client,
)

__all__ = [
    "ClientSlotConflictError",
    "ClientSlotError",
    "ClientSlotNotFoundError",
    "activate_client_slot",
    "create_client_slot",
    "delete_client_slot",
    "get_active_client",
    "list_client_slots",
    "save_active_client",
]
