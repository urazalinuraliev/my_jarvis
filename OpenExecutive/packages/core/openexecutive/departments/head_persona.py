"""Per-department head persona helpers.

When a department has an identified head person, the Executive can address
that person using a tailored voice.  This module wires up a placeholder
``agent_override`` row keyed ``department:{slug}:head`` so the override API
and UI can surface it — the system_prompt_suffix (voice content) is empty by
default and should be filled in by the operator.

Phase 8 scope: placeholder creation only.  Actual voice injection into
specialist prompts is a future phase.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_head_persona_override(
    department_slug: str,
    person_id: int,
    db_path: Path | None = None,
) -> bool:
    """Create a ``department:{slug}:head`` override placeholder if none exists.

    Returns True if a new row was created, False if one already existed
    (idempotent — never overwrites an operator's customised override).

    The override is intentionally minimal: only a role label is set.  The
    prompt/voice content is left None so existing specialist behaviour is
    unchanged until an operator deliberately fills it in.
    """
    from openexecutive.agents.overrides import (
        get_override,
        initialize_overrides_db,
        invalidate_cache,
        set_override,
    )

    agent_id = f"department:{department_slug}:head"
    initialize_overrides_db(db_path=db_path)
    # Invalidate the in-process cache so we read the authoritative DB state —
    # another worker or a prior `set_override` call may have created the row
    # without this process's cache reflecting it.
    invalidate_cache()

    existing = get_override(agent_id, db_path=db_path)
    if existing is not None:
        logger.debug(
            "head_persona: override %r already exists — skipping", agent_id
        )
        return False

    set_override(
        agent_id,
        role=f"Head of {department_slug.replace('_', ' ').title()} (person {person_id})",
        role_set=True,
        db_path=db_path,
    )
    logger.info(
        "head_persona: created placeholder override %r for person_id=%d",
        agent_id, person_id,
    )
    return True
