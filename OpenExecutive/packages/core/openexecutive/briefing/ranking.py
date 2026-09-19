"""Score and categorize briefing proposals.

The briefing was drowning in low-signal watchlist/stock alerts ("X moved
4.8%, no obvious driver") that are unrouted — so they pile into the
principal's "Needs you" queue and crowd out work that genuinely needs a
decision. This module separates the two:

  - ``category`` — ``"action"`` (a human should look) vs ``"monitoring"``
    (passive awareness; safe to collapse). Watchlist/external signals that
    are unrouted and not high-severity are ``monitoring``.
  - ``score`` — a sort key (higher = more attention). Severity dominates;
    a routed/assigned alert and recency add weight. Used to order the
    ``action`` queue so the sharpest item leads.

Pure functions — no I/O — so they are trivial to unit test and cheap to
call per alert inside ``_build_today``.
"""
from __future__ import annotations

from typing import Any

# Severity → base weight. Mirrors AlertSeverity ("low"/"medium"/"high"/
# "urgent"); unknown strings fall back to the medium band so a new
# severity never silently sinks to the bottom.
_SEVERITY_WEIGHT: dict[str, int] = {
    "low": 10,
    "medium": 40,
    "high": 70,
    "urgent": 100,
}
_DEFAULT_SEVERITY_WEIGHT = 40

# A routed/assigned alert is a deliberate hand-off — weight it above an
# unrouted catch-all of the same severity.
_ROUTED_BONUS = 15

# Severities that keep an external/watchlist signal in the "action" lane
# even when unrouted — a competitor's stock cratering IS worth a look.
_ACTION_SEVERITIES = frozenset({"high", "urgent"})


# Source kinds emitted by the monitoring pipeline's adapters — kept in sync
# with the SOURCE_KIND_* constants in ``openexecutive.monitoring.models``
# (plus the generic ``"watchlist"`` tag). Adding a new adapter without listing
# it here is what silently kept its low/medium signals out of the Monitoring
# lane — they fell through to ``"action"`` instead.
_EXTERNAL_SOURCES = frozenset({
    "stock", "vendor_status", "rss", "watchlist", "query", "edgar", "page_watch",
})


def _is_external_signal(source: str, topic_tags: list[str]) -> bool:
    """True for passively-monitored signals (watchlist stock/RSS/vendor/query/…).

    These come from the monitoring pipeline rather than a human/triage
    decision: ``source`` is one of the adapter kinds in ``_EXTERNAL_SOURCES``
    (``"stock"`` / ``"vendor_status"`` / ``"rss"`` / ``"query"`` / ``"edgar"`` /
    ``"page_watch"``), or any ``external:*`` topic tag (e.g.
    ``external:stock-aapl``).
    """
    if source in _EXTERNAL_SOURCES:
        return True
    return any(t.startswith("external:") for t in topic_tags)


def categorize(
    *,
    source: str,
    severity: str,
    routed_to_person_id: int | None,
    topic_tags: list[str],
) -> str:
    """Return ``"action"`` or ``"monitoring"`` for one alert.

    An item is ``monitoring`` only when it is a passively-monitored
    external signal, AND nobody was assigned it, AND it is not high/urgent.
    Anything a human or triage explicitly routed, and anything high-severity,
    stays ``action`` — we never hide something that was deliberately surfaced.
    """
    if routed_to_person_id is not None:
        return "action"
    if severity in _ACTION_SEVERITIES:
        return "action"
    if _is_external_signal(source, topic_tags):
        return "monitoring"
    return "action"


# Human notes for an external signal that landed in "action" *because of
# its severity* (not routing). Keyed off severity so the copy stays
# decoupled from the stock adapter's %-thresholds (≥5% → high, ≥10% →
# urgent live in monitoring/sources/stock.py).
_SURFACED_BY_SEVERITY: dict[str, str] = {
    "high": (
        "Surfaced here because of a large market move — "
        "normally this sits in Monitoring."
    ),
    "urgent": (
        "Surfaced here because of a major market move — "
        "normally this sits in Monitoring."
    ),
}


def surfaced_reason(
    *,
    source: str,
    severity: str,
    routed_to_person_id: int | None,
    topic_tags: list[str],
) -> str | None:
    """Explain why an external signal is in "Needs you" instead of Monitoring.

    Returns a short note only when an external/watchlist signal was pulled
    into the ``action`` lane *because of its severity* — i.e. it is external,
    unrouted, and high/urgent (the escape hatch in :func:`categorize`). In
    every other case (routed items, low/medium externals that already sit in
    Monitoring, non-external action items) there is nothing to explain, so it
    returns ``None``.
    """
    if routed_to_person_id is not None:
        return None
    if severity not in _ACTION_SEVERITIES:
        return None
    if not _is_external_signal(source, topic_tags):
        return None
    return _SURFACED_BY_SEVERITY.get(severity)


def score(
    *,
    severity: str,
    routed_to_person_id: int | None,
) -> int:
    """Attention sort key for the ``action`` queue (higher leads)."""
    base = _SEVERITY_WEIGHT.get(severity, _DEFAULT_SEVERITY_WEIGHT)
    if routed_to_person_id is not None:
        base += _ROUTED_BONUS
    return base


def score_and_categorize(alert: Any) -> tuple[int, str, str | None]:
    """Convenience wrapper over an ``Alert``-shaped object.

    Reads ``source``, ``severity``, ``routed_to_person_id`` and
    ``topic_tags`` defensively so it works on both the Pydantic ``Alert``
    model and a plain dict. Returns ``(score, category, surfaced_reason)``;
    ``surfaced_reason`` is ``None`` unless an external signal was pulled
    into the action lane by its severity.
    """
    def _get(name: str, default: Any) -> Any:
        if isinstance(alert, dict):
            return alert.get(name, default)
        return getattr(alert, name, default)

    source = str(_get("source", "") or "")
    severity = str(_get("severity", "medium") or "medium")
    routed = _get("routed_to_person_id", None)
    topic_tags = list(_get("topic_tags", []) or [])

    return (
        score(severity=severity, routed_to_person_id=routed),
        categorize(
            source=source,
            severity=severity,
            routed_to_person_id=routed,
            topic_tags=topic_tags,
        ),
        surfaced_reason(
            source=source,
            severity=severity,
            routed_to_person_id=routed,
            topic_tags=topic_tags,
        ),
    )


__all__ = ["categorize", "score", "score_and_categorize", "surfaced_reason"]
