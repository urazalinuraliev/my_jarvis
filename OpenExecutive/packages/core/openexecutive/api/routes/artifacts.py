"""HTTP surface for the Executive Artifacts section.

A read-only, unified view over the two places the Executive already stores
Markdown deliverables — no new table, the underlying rows stay canonical:

1. `draft_artifact` documents, written to the alerts table
   (`source='artifact'`), and
2. completed workflow runs, whose Markdown lives in
   `workflow_runs.artifact`.

Both sources are merged, sorted newest-first, and addressed by a composite
id `"{kind}:{native_id}"` (`alert:<int>` / `run:<hex>`). The `kind` prefix
doubles as the dispatch key for every per-artifact route. The native id
spaces are colon-free, so the scheme is unambiguous and reversible.

Archive is a reversible soft-hide (a nullable `archived_at` column on each
backing table); delete is a permanent hard-delete of the underlying row.
The default list shows only active artifacts; `?archived=true` shows only
archived ones. Every mutating route refuses non-artifact alert ids the same
way the detail route does — these routes must not become general
alert/run mutators.

Endpoints:
- GET    /artifacts                       Unified list (summaries, no bodies)
- GET    /artifacts/{composite_id}        One artifact with its full Markdown body
- POST   /artifacts/{composite_id}/archive   Soft-hide (reversible)
- POST   /artifacts/{composite_id}/restore   Un-archive
- DELETE /artifacts/{composite_id}        Permanently delete the underlying row
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from openexecutive.alerts.models import Alert
from openexecutive.alerts.store import (
    delete_alert,
    get_alert,
    list_artifact_alerts,
    set_alert_archived,
)
from openexecutive.alerts.store import (
    initialize_db as initialize_alerts_db,
)
from openexecutive.workflows.persistence import (
    delete_run,
    get_run,
    initialize_runs_db,
    list_artifact_runs,
    set_run_archived,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_DRAFT_SOURCE_LABEL = "Drafted by Executive"
# Max artifacts returned by the list endpoint (mirrors alerts.list_alerts' cap).
_DEFAULT_LIMIT = 200
# Chars of body shown as a card preview. Unrelated to _DEFAULT_LIMIT despite
# the shared value — keep them as separate named knobs.
_PREVIEW_CHARS = 200


class ArtifactSummary(BaseModel):
    id: str
    kind: Literal["draft", "workflow"]
    title: str
    source_label: str
    created_at: str
    preview: str | None = None
    status: str
    severity: str | None = None
    # ISO timestamp when archived; None = active. Lets the detail page show
    # Archive vs Restore correctly and keeps the TS interface honest.
    archived_at: str | None = None


class ArtifactDetail(ArtifactSummary):
    body: str
    rationale: str | None = None


@router.get("/artifacts")
async def list_artifacts(
    limit: int = _DEFAULT_LIMIT, archived: bool = False
) -> dict[str, list[ArtifactSummary]]:
    """Unified, newest-first list of every artifact the Executive produced.

    Defaults to active artifacts; `?archived=true` returns only archived ones
    (the gallery's Active / Archived views are clean swaps, not supersets).
    """
    initialize_alerts_db()
    initialize_runs_db()

    items: list[ArtifactSummary] = []

    for alert in list_artifact_alerts(limit=limit, archived=archived):
        items.append(
            ArtifactSummary(
                id=f"alert:{alert.id}",
                kind="draft",
                title=alert.headline,
                source_label=_DRAFT_SOURCE_LABEL,
                created_at=alert.created_at,
                preview=_preview(alert.body) or None,
                status=alert.status,
                severity=alert.severity,
                archived_at=alert.archived_at,
            )
        )

    for run in list_artifact_runs(limit=limit, archived=archived):
        items.append(
            ArtifactSummary(
                id=f"run:{run['run_id']}",
                kind="workflow",
                title=run["title"],
                source_label=run["workflow_name"],
                created_at=run["created_at"],
                # Body excluded from the run list query — title + workflow carry the card.
                preview=None,
                status="done",
                severity=None,
                archived_at=run.get("archived_at"),
            )
        )

    items.sort(key=lambda a: a.created_at, reverse=True)
    return {"artifacts": items[:limit]}


@router.get("/artifacts/{composite_id}")
async def get_artifact(composite_id: str) -> ArtifactDetail:
    """One artifact with its full Markdown body, addressed by composite id."""
    kind, native_id = _parse_composite_id(composite_id)

    if kind == "alert":
        alert = _require_artifact_alert(native_id, composite_id)
        return ArtifactDetail(
            id=f"alert:{alert.id}",
            kind="draft",
            title=alert.headline,
            source_label=_DRAFT_SOURCE_LABEL,
            created_at=alert.created_at,
            preview=_preview(alert.body) or None,
            status=alert.status,
            severity=alert.severity,
            archived_at=alert.archived_at,
            body=alert.body,
            rationale=alert.suggested_action or None,
        )

    run = _require_artifact_run(native_id, composite_id)
    return ArtifactDetail(
        id=f"run:{run['run_id']}",
        kind="workflow",
        title=run["title"],
        source_label=run["workflow_name"],
        created_at=run["created_at"],
        preview=None,
        status="done",
        severity=None,
        archived_at=run.get("archived_at"),
        body=run["artifact"],
        rationale=None,
    )


@router.post("/artifacts/{composite_id}/archive")
async def archive_artifact(composite_id: str) -> dict[str, str]:
    """Soft-hide an artifact (reversible). Drops it from the default list."""
    _set_artifact_archived(composite_id, archived=True)
    return {"status": "archived", "id": composite_id}


@router.post("/artifacts/{composite_id}/restore")
async def restore_artifact(composite_id: str) -> dict[str, str]:
    """Un-archive an artifact, returning it to the active list."""
    _set_artifact_archived(composite_id, archived=False)
    return {"status": "restored", "id": composite_id}


@router.delete("/artifacts/{composite_id}")
async def delete_artifact(composite_id: str) -> dict[str, str]:
    """Permanently delete the underlying alert / workflow-run row."""
    kind, native_id = _parse_composite_id(composite_id)
    if kind == "alert":
        alert = _require_artifact_alert(native_id, composite_id)
        assert alert.id is not None  # loaded from DB — id is always set
        delete_alert(alert.id)  # existence already validated above
    else:
        run = _require_artifact_run(native_id, composite_id)
        delete_run(run["run_id"])
    return {"status": "deleted", "id": composite_id}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _parse_composite_id(composite_id: str) -> tuple[str, str]:
    """Split `"{kind}:{native_id}"` into its parts, or 400 if malformed.

    Validates only the shape (known kind prefix + non-empty native id); the
    per-kind native-id validation (e.g. alert ids must be ints) and the
    artifact-existence check live in `_require_artifact_*`.
    """
    kind, sep, native_id = composite_id.partition(":")
    if not sep or kind not in ("alert", "run") or not native_id:
        raise HTTPException(
            status_code=400, detail=f"Malformed artifact id: {composite_id!r}"
        )
    return kind, native_id


def _require_artifact_alert(native_id: str, composite_id: str) -> Alert:
    """Load an alert-backed artifact or raise: 400 on bad id, 404 otherwise.

    404s a non-artifact alert id (`source != 'artifact'`) so neither the
    detail route nor any mutating route can reach a general alert row.
    """
    try:
        alert_id = int(native_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Malformed artifact id: {composite_id!r}"
        ) from exc
    alert = get_alert(alert_id)
    if alert is None or alert.source != "artifact":
        raise HTTPException(
            status_code=404, detail=f"Artifact {composite_id!r} not found"
        )
    return alert


def _require_artifact_run(native_id: str, composite_id: str) -> dict[str, Any]:
    """Load a run-backed artifact or 404. An empty body counts as no artifact."""
    run = get_run(native_id)
    if run is None or not run.get("artifact"):
        raise HTTPException(
            status_code=404, detail=f"Artifact {composite_id!r} not found"
        )
    return run


def _set_artifact_archived(composite_id: str, *, archived: bool) -> None:
    """Archive or restore an artifact, dispatching on the composite-id kind."""
    kind, native_id = _parse_composite_id(composite_id)
    if kind == "alert":
        alert = _require_artifact_alert(native_id, composite_id)
        assert alert.id is not None  # loaded from DB — id is always set
        set_alert_archived(alert.id, archived)
    else:
        run = _require_artifact_run(native_id, composite_id)
        set_run_archived(run["run_id"], archived)


def _preview(markdown: str, n: int = _PREVIEW_CHARS) -> str:
    """A short plain-ish preview: strip leading heading marks / whitespace."""
    text = (markdown or "").lstrip()
    # Drop a single leading '# ...' heading line so the preview isn't just the title.
    if text.startswith("#"):
        first_break = text.find("\n")
        if first_break != -1:
            text = text[first_break + 1 :].lstrip()
    collapsed = " ".join(text.split())
    return collapsed[:n]
