"""HTTP surface for the static architecture page.

Endpoints:
- GET  /architecture/sections                 List sections + availability
- GET  /architecture/sections/{section_id}    Get one section's content

Content is pre-authored and version-controlled under
``architecture/prebuilt/*.json`` and served read-only — a section
request is a plain file read. No LLM calls happen on this path; to
update a section, edit its file and ship it.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from openexecutive.architecture import prebuilt
from openexecutive.architecture.sections import SECTIONS, get_section

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/architecture/sections")
async def list_sections() -> dict[str, Any]:
    """Directory listing of architecture sections with availability.

    A cheap read of the pre-authored content files — generates nothing.
    `fresh` reports whether a section has authored content on disk."""
    available = prebuilt.list_prebuilt()
    out: list[dict[str, Any]] = []
    for spec in SECTIONS:
        content = available.get(spec.id)
        out.append(
            {
                "id": spec.id,
                "title": spec.title,
                "sub": spec.sub,
                "wants_mermaid": spec.wants_mermaid,
                "diagram_kind": spec.diagram_kind,
                "generated_at": content.get("generated_at") if content else None,
                "fresh": content is not None,
            }
        )
    return {"sections": out}


@router.get("/architecture/sections/{section_id}")
async def get_section_content(section_id: str) -> dict[str, Any]:
    """Return the pre-authored content for one section."""
    try:
        spec = get_section(section_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    content = prebuilt.get_prebuilt(spec.id)
    if content is None:
        logger.warning("architecture.prebuilt.missing section=%s", spec.id)
        raise HTTPException(
            status_code=404,
            detail=f"No pre-authored content for section: {spec.id}",
        )
    return content
