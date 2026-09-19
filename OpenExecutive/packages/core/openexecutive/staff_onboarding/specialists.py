"""Resolve which specialist lens tailors a role's onboarding.

Generalizes to any role (not just C-suite): a department's configured
``specialist_key`` wins when known, otherwise a function-name map, otherwise the
strategy chief (``cso``) as a thoughtful-but-generic fallback. Every role
therefore gets *some* specialist lens.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Human-friendly function names → specialist registry keys. Mirrors the intent
# of talent's exec_search_brief map; kept local so the onboarding subsystem
# doesn't import a private name from a talent workflow.
FUNCTION_TO_SPECIALIST: dict[str, str] = {
    "engineering": "cpo",   # closest available — no CTO specialist
    "product": "cpo",
    "design": "cpo",
    "marketing": "cmo",
    "sales": "cmo",         # closest available — no CRO specialist
    "revenue": "cmo",
    "operations": "coo",
    "ops": "coo",
    "finance": "cfo",
    "accounting": "cfo",
    "strategy": "cso",
    "legal": "gc",
    "people": "chro",
    "hr": "chro",
    "talent": "chro",
}

_FALLBACK = "cso"


def _from_text(text: str) -> str | None:
    """Best-effort: match any known function keyword appearing in free text."""
    low = (text or "").lower()
    for key, specialist in FUNCTION_TO_SPECIALIST.items():
        if key in low:
            return specialist
    return None


def resolve_specialist(
    *,
    role: str = "",
    function: str = "",
    department: str = "",
    db_path: Path | None = None,
) -> str:
    """Resolve the lead specialist for a role.

    Precedence: department's configured ``specialist_key`` → explicit
    ``function`` → keywords in ``department``/``role`` text → ``cso`` fallback.
    """
    if department:
        try:
            from openexecutive.departments import store as dept_store

            dept = dept_store.get_department(department, db_path=db_path)
            if dept is not None and dept.config.specialist_key:
                return dept.config.specialist_key
        except Exception:
            logger.exception("staff_onboarding: department specialist lookup failed")

    if function:
        mapped = FUNCTION_TO_SPECIALIST.get(function.strip().lower()) or _from_text(function)
        if mapped:
            return mapped

    for text in (department, role):
        mapped = _from_text(text)
        if mapped:
            return mapped

    return _FALLBACK
