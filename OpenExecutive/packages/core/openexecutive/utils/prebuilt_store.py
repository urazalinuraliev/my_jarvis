"""Read-only store for pre-authored, version-controlled doc sections.

Several surfaces in the app are rendered from static JSON files that ship
in the image rather than generated at request time — the ``/architecture``
technical reference and the ``/guide`` user guide both work this way.
Serving a section is a plain file read; nothing on this path calls an LLM.

Each file is a JSON object with the keys ``section_id``, ``title``,
``markdown``, ``mermaid`` (string or null), and ``generated_at`` (ISO-8601).
To update a section, edit its ``<id>.json`` file and ship it.

``PrebuiltDocStore`` is the shared loader behind those surfaces; each one
points it at its own directory of section files.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {"section_id", "title", "markdown", "mermaid", "generated_at"}


class PrebuiltDocStore:
    """Loads pre-authored section JSON from a single directory.

    The store never trusts its caller's ``section_id``: it rejects path
    separators and dot segments so a section id can only ever resolve to a
    flat ``<id>.json`` file inside ``directory`` (defence-in-depth against
    path traversal — callers also validate against a section registry).
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _read_file(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("prebuilt.read_error path=%s", path)
            return None
        if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data):
            logger.error("prebuilt.bad_shape path=%s", path)
            return None
        return data

    def get(self, section_id: str) -> dict[str, Any] | None:
        """Return the authored content dict for one section, or ``None`` if
        the file is absent or malformed."""
        if "/" in section_id or "\\" in section_id or section_id in ("", ".", ".."):
            return None
        path = self._dir / f"{section_id}.json"
        if not path.is_file():
            return None
        return self._read_file(path)

    def list(self) -> dict[str, dict[str, Any]]:
        """Map of ``section_id`` -> authored content for every readable file
        in the directory. Cheap; safe to call per request.

        Keyed by filename stem (consistent with ``get``, which addresses
        files by ``<id>.json``) rather than the file's internal
        ``section_id`` field."""
        out: dict[str, dict[str, Any]] = {}
        if not self._dir.is_dir():
            return out
        for path in sorted(self._dir.glob("*.json")):
            data = self._read_file(path)
            if data is not None:
                out[path.stem] = data
        return out
