"""Read-only loader for the pre-authored architecture-page content.

The ``/architecture`` page is served from static, version-controlled JSON
files under ``architecture/prebuilt/`` — authored by hand and shipped in
the image. Serving a section is a plain file read; nothing in this path
calls an LLM. To update a section, edit its ``prebuilt/<id>.json`` file
and ship it.

The actual file loading lives in the shared
``openexecutive.utils.prebuilt_store.PrebuiltDocStore`` (also used by the
``/guide`` user-guide surface); this module just points it at the
architecture directory and keeps the historical function-level API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openexecutive.utils.prebuilt_store import PrebuiltDocStore

_STORE = PrebuiltDocStore(Path(__file__).parent / "prebuilt")


def get_prebuilt(section_id: str) -> dict[str, Any] | None:
    """Return the authored content dict for one section, or ``None`` if
    the file is absent or malformed."""
    return _STORE.get(section_id)


def list_prebuilt() -> dict[str, dict[str, Any]]:
    """Map of ``section_id`` -> authored content for every readable file
    in the prebuilt directory. Cheap; safe to call per request."""
    return _STORE.list()
