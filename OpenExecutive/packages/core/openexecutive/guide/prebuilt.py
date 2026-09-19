"""Read-only loader for the pre-authored user-guide content.

The ``/guide`` page is served from static, version-controlled JSON files
under ``guide/prebuilt/`` — authored by hand and shipped in the image.
Serving a section is a plain file read; nothing in this path calls an LLM.
To update a section, edit its ``prebuilt/<id>.json`` file and ship it.

File loading lives in the shared
``openexecutive.utils.prebuilt_store.PrebuiltDocStore`` (also used by the
``/architecture`` reference); this module points it at the guide directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openexecutive.utils.prebuilt_store import PrebuiltDocStore

_STORE = PrebuiltDocStore(Path(__file__).parent / "prebuilt")


def get_prebuilt(section_id: str) -> dict[str, Any] | None:
    """Return the authored content dict for one guide section, or ``None``
    if the file is absent or malformed."""
    return _STORE.get(section_id)


def list_prebuilt() -> dict[str, dict[str, Any]]:
    """Map of ``section_id`` -> authored content for every readable file in
    the guide directory. Cheap; safe to call per request."""
    return _STORE.list()
