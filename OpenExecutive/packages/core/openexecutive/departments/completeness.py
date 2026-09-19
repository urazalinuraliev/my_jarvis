"""Org-completeness check — warns at boot about under-configured departments/people.

Called from ``api/main.py`` lifespan after seeding. Each warning is logged at
WARNING level so it appears in the boot log without blocking startup.

Checks performed
----------------
1. Any department without a ``head_person_id`` set.
2. Any non-WILDCARD ``AuthorityScope`` token that has zero non-principal approvers
   (i.e. the only fallback is the principal).  The principal always has WILDCARD,
   so every scope has at least the principal — but that defeats the purpose of
   routing work to fractional executives.

Returns a list of human-readable warning strings (empty list means all clear).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def check_org_completeness(db_path: Path | None = None) -> list[str]:
    """Return a list of completeness-warning strings, empty if all clear."""
    from openexecutive.departments.store import list_departments
    from openexecutive.people.models import AuthorityScope
    from openexecutive.people.store import find_approvers

    warnings: list[str] = []

    # ------------------------------------------------------------------ #
    # 1. Departments without a head person
    # ------------------------------------------------------------------ #
    try:
        depts = list_departments(db_path=db_path)
        for dept_state in depts:
            if dept_state.config.head_person_id is None:
                warnings.append(
                    f"Department '{dept_state.config.title}' has no head person configured."
                )
    except Exception:
        logger.warning("completeness: could not load departments", exc_info=True)

    # ------------------------------------------------------------------ #
    # 2. Authority scope tokens with no non-principal approver
    # ------------------------------------------------------------------ #
    try:
        non_wildcard = [s for s in AuthorityScope if s != AuthorityScope.WILDCARD]
        for scope in non_wildcard:
            approvers = find_approvers(scope, db_path=db_path)
            # find_approvers sorts by is_principal ASC — non-principals first.
            # If every approver is a principal (or list is empty), warn.
            has_non_principal = any(not p.is_principal for p in approvers)
            if not has_non_principal:
                warnings.append(
                    f"No non-principal approver for scope '{scope.value}'."
                )
    except Exception:
        logger.warning("completeness: could not check authority scopes", exc_info=True)

    return warnings
