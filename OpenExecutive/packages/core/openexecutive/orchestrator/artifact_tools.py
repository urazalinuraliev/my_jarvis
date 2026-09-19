"""Chat + research tool: author a document the Executive wants reviewed.

`draft_artifact` lets the Executive write a standalone Markdown deliverable
— a memo, brief, or competitor teardown it judged worth the principal's
time — and surface it for review. Unlike `create_alert`, it writes the
document DIRECTLY to the alerts table (bypassing the triage pipeline) so
the authored text is never suppressed or rewritten, then routes it to the
principal so it lands in the `/today` "Needs you" queue.

The artifact rides the existing alert -> /today -> ProposalCard path. The
`["artifact"]` topic tag is the UI discriminator (same convention as the
`external:*` tags) so the card can render the body as a document rather
than a terse proposal — no new table, no new endpoint.

Registered in `_ALL_SKILL_TOOLS` / `_ALL_SKILL_HANDLERS`, so it is
available in BOTH the chat tool loop and the executive_research synthesis
loop (both consume those registries).
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


DRAFT_ARTIFACT_TOOL: dict[str, Any] = {
    "name": "draft_artifact",
    "description": (
        "Author a standalone document you researched and judged worth "
        "the principal's review — a memo, brief, or competitor teardown. "
        "Use this (NOT create_alert) when you have a real written "
        "deliverable, not just a one-line operational signal. The "
        "document lands verbatim in the principal's '/today' review queue "
        "with your rationale attached; it does NOT page or DM anyone, so "
        "use it for 'please read when you can', not urgent interrupts. "
        "Reserve it for findings that clear a high interest bar — quiet "
        "is the right default."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short document title — the card heading.",
            },
            "document": {
                "type": "string",
                "description": (
                    "The full deliverable in Markdown. Headings, lists, "
                    "and tables are fine — it renders as a document."
                ),
            },
            "why_interesting": {
                "type": "string",
                "description": (
                    "1-2 sentences: why this is worth the principal's "
                    "time. Shown as the 'Why this is worth your time' "
                    "block above the document."
                ),
            },
            "source_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional provenance URLs you verified. Appended as a "
                    "'Sources' footer to the document."
                ),
            },
            "severity": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Attention weight in the queue. Default 'medium'.",
            },
        },
        "required": ["title", "document", "why_interesting"],
    },
}


async def handle_draft_artifact(tool_input: dict[str, Any]) -> str:
    from openexecutive.alerts.models import AlertSeverity
    from openexecutive.alerts.store import insert_alert
    from openexecutive.audit import log_event as audit_log
    from openexecutive.people.store import find_principal_person

    title = str(tool_input.get("title", "")).strip()
    document = str(tool_input.get("document", "")).strip()
    why_interesting = str(tool_input.get("why_interesting", "")).strip()
    if not title or not document or not why_interesting:
        return _err("title, document, and why_interesting are required")

    severity_raw = str(tool_input.get("severity") or "medium").strip().lower()
    try:
        severity = AlertSeverity(severity_raw)
    except ValueError:
        severity = AlertSeverity.MEDIUM

    body = _with_sources_footer(document, tool_input.get("source_urls"))

    principal_id: int | None = None
    try:
        principal = find_principal_person()
        principal_id = principal.id if principal else None
    except Exception:
        logger.exception("draft_artifact: principal lookup failed")

    try:
        alert_id = insert_alert(
            source="artifact",
            external_id=str(uuid.uuid4()),
            severity=severity.value,
            headline=title[:160],
            body=body,
            suggested_action=why_interesting,
            topic_tags=["artifact"],
            routed_to_person_id=principal_id,
        )
    except Exception as exc:
        logger.exception("draft_artifact: insert failed")
        _audit(audit_log, False, f"draft_artifact FAILED: {title[:120]} — {exc}",
               {"error": str(exc)[:300]})
        return _err(f"insert failed: {exc}")

    _audit(
        audit_log,
        True,
        f"Drafted artifact for review: {title[:160]}",
        {
            "alert_id": alert_id,
            "severity": severity.value,
            "routed_to_person_id": principal_id,
            "body_chars": len(body),
        },
    )
    logger.info("draft_artifact: alert_id=%s title=%r", alert_id, title)
    return json.dumps({"ok": True, "alert_id": alert_id, "title": title})


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _with_sources_footer(document: str, source_urls: Any) -> str:
    if not isinstance(source_urls, list):
        return document
    urls = [str(u).strip() for u in source_urls if str(u).strip()]
    if not urls:
        return document
    footer = "\n\n### Sources\n" + "\n".join(f"- {u}" for u in urls)
    return document + footer


def _err(msg: str) -> str:
    return json.dumps({"error": msg})


def _audit(audit_log: Any, ok: bool, summary: str, details: dict[str, Any]) -> None:
    audit_log(
        "tool_invocation",
        summary,
        actor="executive",
        details={"tool": "draft_artifact", "ok": ok, **details},
    )


DRAFT_ARTIFACT_TOOLS: list[dict[str, Any]] = [DRAFT_ARTIFACT_TOOL]

DRAFT_ARTIFACT_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "draft_artifact": handle_draft_artifact,
}


__all__ = [
    "DRAFT_ARTIFACT_TOOL",
    "DRAFT_ARTIFACT_TOOLS",
    "DRAFT_ARTIFACT_TOOL_HANDLERS",
    "handle_draft_artifact",
]
