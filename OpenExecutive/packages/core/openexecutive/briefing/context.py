"""Compact open-alert digest for the chat user turn.

The ``/today`` page shows a synthesized "What's going on" narrative whose items
(e.g. "Gulf Coast Port Cyberattack") are drawn from the open alerts queue — the
same rows that render as proposal cards below it. But ``/chat`` never saw that
data, so when the principal clicked a briefing item (or just typed its name) the
Executive had no record of it and couldn't discuss it.

This renders the current open alerts into a compact ``<briefing>`` block that the
chat route injects into the **user turn** (never a cached system block, so prompt
caching is unaffected). It mirrors how ``/today`` builds proposals
(`api/routes/today.py`): company-wide, ``status="unread"``.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Cap each alert body so a wordy proposal can't blow the context budget; the
# headline + suggested_action carry the gist and the user can open the card for
# the full text.
_BODY_SNIPPET_CHARS = 200

# Cap how many open alerts the digest carries. The board rarely holds this many
# unread items at once; the ceiling just bounds the per-turn token cost.
_MAX_ALERTS = 30


def format_open_alerts_for_prompt(db_path: Path | None = None, limit: int = _MAX_ALERTS) -> str:
    """Render current open (unread) alerts as a compact digest, or ``""`` when none.

    One line per alert::

        [<id>] (<category>) <headline> — <body snippet> | suggested: ... | tags: ...

    Company-wide and scoped to ``status="unread"``, mirroring ``/today``'s
    proposal build. ``category`` (``action``/``monitoring``) comes from
    :func:`openexecutive.briefing.ranking.score_and_categorize` so the Executive
    can tell an item awaiting a decision from a passive monitoring signal.

    Pure synchronous SQLite read — wrap in ``asyncio.to_thread`` at the call
    site. Never raises: any failure logs and returns ``""`` so a chat turn is
    never blocked by an alerts-store hiccup.
    """
    from openexecutive.alerts.store import list_alerts
    from openexecutive.briefing.ranking import score_and_categorize

    try:
        alerts = list_alerts(status="unread", limit=limit, db_path=db_path)
    except Exception:
        logger.exception("briefing_context.list_alerts_failed")
        return ""

    lines: list[str] = []
    for alert in alerts:
        _score, category, _reason = score_and_categorize(alert)
        body = (alert.body or "").strip().replace("\n", " ")
        if len(body) > _BODY_SNIPPET_CHARS:
            body = body[:_BODY_SNIPPET_CHARS].rstrip() + "…"
        line = f"[{alert.id}] ({category}) {alert.headline}"
        if body:
            line += f" — {body}"
        if alert.suggested_action:
            line += f" | suggested: {alert.suggested_action.strip()}"
        if alert.topic_tags:
            line += f" | tags: {', '.join(alert.topic_tags)}"
        lines.append(line)

    if not lines:
        return ""

    header = (
        "Open items currently on the briefing board — the principal sees these "
        "as cards and as the 'What's going on' summary on /today. Each line is "
        "[alert_id] (category) headline — details. When the user asks about one "
        "of these by name, this is what they mean."
    )
    return header + "\n" + "\n".join(lines)


__all__ = ["format_open_alerts_for_prompt"]
