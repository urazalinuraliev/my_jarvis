"""Proactive nudge engine — periodic heartbeat that decides what to chase.

The Executive used to be purely reactive: it only sent proactive messages
when the user explicitly asked for a follow-up (`schedule_followup`),
when a department cadence fired (`dept_cadence`), or when an alert was
triaged. Stalled workflows, open commitments, and idle initiatives sat
silently. This module fills that gap.

A `kind="nudge_scan"` scheduled action fires every
``NUDGE_SCAN_INTERVAL_MINUTES`` (default 15) from the existing scheduler
runner. Each tick:

  1. Deterministically selects candidates from three sources:
       a) ``workflow_runs`` rows with ``status='awaiting_human'`` whose
          timeout is within ``NUDGE_STALLED_LEAD_HOURS`` and whose last
          update is older than ``NUDGE_STALLED_MIN_QUIET_HOURS``.
       b) ``scheduled_actions`` rows with ``awaiting_response_since``
          older than ``NUDGE_COMMITMENT_STALE_DAYS``.
       c) Active initiatives whose ``updated_at`` is older than
          ``NUDGE_INITIATIVE_IDLE_DAYS`` (and whose dept cadence
          hasn't refreshed them in the meantime).

  2. Dedups each candidate against past nudges via the ``scope_key``
     column on ``scheduled_actions`` and per-source cooldowns.

  3. Picks a delivery channel per candidate via
     ``people.channel.prefer_channel_for`` — respecting availability
     windows and quiet hours. Defers via ``next_available_window`` when
     the assignee is temporarily unreachable.

  4. Emits ``kind="proactive_nudge"`` rows with the resolved
     ``(channel, channel_ref, run_at)``. The scheduler runner's existing
     ad-hoc dispatch path picks them up and asks the Executive to write
     and send the actual message — no new delivery code path.

This mirrors ``departments/cadence.py`` (``bootstrap_cadences``,
``enqueue_next``) and reuses the runner's polling / claim / retry
machinery, so there is no second background loop and no separate
single-worker contract.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Scope-key prefixes per source. Used both when minting the key and when
# scanning historical rows to dedup.
SCOPE_PREFIX_STALLED = "nudge:stalled"
SCOPE_PREFIX_COMMITMENT = "nudge:commitment"
SCOPE_PREFIX_INITIATIVE = "nudge:initiative"

# Heartbeat row identity. Channel/ref are constants so bootstrap is idempotent
# via the same "is there already a pending row?" check used by dept cadences.
HEARTBEAT_KIND = "nudge_scan"
HEARTBEAT_CHANNEL = "__internal__"
HEARTBEAT_CHANNEL_REF = "nudge_engine"
HEARTBEAT_INTENT = "Proactive nudge engine — periodic scan."


@dataclass(frozen=True)
class NudgeCandidate:
    """A single proactive nudge the scan has decided to emit."""
    scope_key: str
    intent_text: str
    source: str  # "stalled" | "commitment" | "initiative"
    urgency_seconds: float  # smaller = more urgent; used for sort
    cooldown: timedelta
    person_id: int | None = None
    originating_session_id: str | None = None
    department: str = ""
    # When person_id is None (only legal for the commitment source) we
    # fall back to the channel the original action already used.
    fallback_channel: str | None = None
    fallback_channel_ref: str | None = None


@dataclass
class _RoutedNudge:
    candidate: NudgeCandidate
    channel: str
    channel_ref: str
    deliver_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Candidate selectors
# ---------------------------------------------------------------------------

def _coerce_aware(dt_or_str: datetime | str | None) -> datetime | None:
    """Parse an ISO string or normalize a naive datetime to UTC-aware."""
    if dt_or_str is None:
        return None
    if isinstance(dt_or_str, str):
        try:
            dt = datetime.fromisoformat(dt_or_str)
        except ValueError:
            return None
    else:
        dt = dt_or_str
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _select_stalled_workflow_candidates(
    now: datetime,
    *,
    lead_hours: int,
    min_quiet_hours: int,
    cooldown_hours: int,
    db_path: Path | None = None,
) -> list[NudgeCandidate]:
    """Workflow runs paused on a human approver whose deadline is near."""
    from openexecutive.workflows.persistence import list_awaiting_runs

    out: list[NudgeCandidate] = []
    lead = timedelta(hours=lead_hours)
    min_quiet = timedelta(hours=min_quiet_hours)
    cooldown = timedelta(hours=cooldown_hours)

    for row in list_awaiting_runs(db_path=db_path):
        person_id = row.get("awaiting_person_id")
        if not person_id:
            continue
        awaiting_until = _coerce_aware(row.get("awaiting_until"))
        if awaiting_until is None or awaiting_until <= now:
            # Already timed out — the resumer handles that; we don't pile on.
            continue
        if awaiting_until - now > lead:
            continue
        updated_at = _coerce_aware(row.get("updated_at"))
        if updated_at is not None and now - updated_at < min_quiet:
            continue
        run_id = row["run_id"]
        title = row.get("title") or row.get("workflow_name") or run_id
        intent = (
            f"Nudge the approver about the paused workflow "
            f'"{title}" (run_id={run_id}). It is awaiting a human '
            f"decision and times out at {awaiting_until.isoformat()}. "
            f"Send ONE concise message: name the workflow, state what's "
            f"needed, and give a clear next action. Do not call "
            f"schedule_followup."
        )
        out.append(
            NudgeCandidate(
                scope_key=f"{SCOPE_PREFIX_STALLED}:{run_id}",
                intent_text=intent,
                source="stalled",
                urgency_seconds=(awaiting_until - now).total_seconds(),
                cooldown=cooldown,
                person_id=int(person_id),
            )
        )
    return out


def _select_stale_commitment_candidates(
    now: datetime,
    *,
    stale_days: int,
    cooldown_hours: int,
    db_path: Path | None = None,
) -> list[NudgeCandidate]:
    """scheduled_actions rows with no reply since `awaiting_response_since`."""
    from openexecutive.memory.episodic import _get_conn, _resolve_db_path

    resolved = _resolve_db_path(db_path)
    if not resolved.exists():
        return []
    cutoff = now - timedelta(days=stale_days)
    cooldown = timedelta(hours=cooldown_hours)

    out: list[NudgeCandidate] = []
    with _get_conn(resolved) as conn:
        rows = conn.execute(
            "SELECT id, channel, channel_ref, intent_text, "
            "originating_session_id, assigned_to_person_id, "
            "awaiting_response_since, department "
            "FROM scheduled_actions "
            "WHERE awaiting_response_since IS NOT NULL "
            "  AND status IN ('pending', 'done') "
            "  AND kind != 'proactive_nudge' "
            "  AND awaiting_response_since <= ? "
            "ORDER BY awaiting_response_since",
            (cutoff.isoformat(),),
        ).fetchall()

    for r in rows:
        awaiting = _coerce_aware(r["awaiting_response_since"])
        if awaiting is None:
            continue
        action_id = r["id"]
        original = (r["intent_text"] or "")[:200]
        intent = (
            f"Chase the open commitment from scheduled action #{action_id}: "
            f'"{original}". No reply since {awaiting.isoformat()}. Send ONE '
            f"polite follow-up that references the original ask and gives a "
            f"clear next action. Do not call schedule_followup."
        )
        out.append(
            NudgeCandidate(
                scope_key=f"{SCOPE_PREFIX_COMMITMENT}:{action_id}",
                intent_text=intent,
                source="commitment",
                # Older awaiting_response_since = more urgent (sort ascending
                # by urgency_seconds, so negate the age in seconds).
                urgency_seconds=-(now - awaiting).total_seconds(),
                cooldown=cooldown,
                person_id=(
                    int(r["assigned_to_person_id"])
                    if r["assigned_to_person_id"] is not None
                    else None
                ),
                originating_session_id=r["originating_session_id"],
                department=r["department"] or "",
                fallback_channel=r["channel"],
                fallback_channel_ref=r["channel_ref"],
            )
        )
    return out


def _dept_cadence_recent(
    slug: str,
    threshold: datetime,
    db_path: Path | None = None,
) -> bool:
    """Did a dept_cadence row for `slug` fire on or after `threshold`?

    Looks at done/running rows — anything still pending hasn't actually
    refreshed the department yet, so doesn't count as a recent pulse.
    """
    from openexecutive.memory.episodic import _get_conn, _resolve_db_path

    resolved = _resolve_db_path(db_path)
    if not resolved.exists():
        return False
    with _get_conn(resolved) as conn:
        row = conn.execute(
            "SELECT 1 FROM scheduled_actions "
            "WHERE kind = 'dept_cadence' AND department = ? "
            "  AND status IN ('done', 'running') "
            "  AND run_at >= ? "
            "LIMIT 1",
            (slug, threshold.isoformat()),
        ).fetchone()
    return row is not None


def _select_idle_initiative_candidates(
    now: datetime,
    *,
    idle_days: int,
    cooldown_days: int,
    db_path: Path | None = None,
) -> list[NudgeCandidate]:
    """Active initiatives that haven't been touched in `idle_days`."""
    from openexecutive.departments import store as dept_store
    from openexecutive.memory.episodic import (
        _resolve_db_path,
        get_active_initiatives,
    )

    threshold = now - timedelta(days=idle_days)
    cooldown = timedelta(days=cooldown_days)
    out: list[NudgeCandidate] = []

    # get_active_initiatives binds db_path at def time; route through the
    # dynamic resolver so monkeypatched DB_PATH actually takes effect.
    resolved_db = _resolve_db_path(db_path)
    for i in get_active_initiatives(db_path=resolved_db):
        # get_active_initiatives is `status != 'completed'`, which includes
        # paused / cancelled / on-hold / planned. We only want to chase
        # initiatives that are genuinely in flight.
        if i.status != "active":
            continue
        updated = _coerce_aware(i.updated_at)
        if updated is None or updated >= threshold:
            continue
        slug = i.department or ""
        if slug and _dept_cadence_recent(slug, threshold, db_path=db_path):
            # The dept's regular check-in covers it; don't pile on.
            continue
        person_id: int | None = None
        if slug:
            state = dept_store.get_department(slug, db_path=db_path)
            if state is not None:
                person_id = state.config.head_person_id
        if person_id is None:
            logger.warning(
                "nudge_engine: initiative %r (id=%s) has no resolvable owner "
                "(department=%r) — skipping",
                i.title, i.id, slug,
            )
            continue
        intent = (
            f'Check in on the active initiative "{i.title}". It is in '
            f"status {i.status!r} and was last updated on "
            f"{i.updated_at[:10]}. Send ONE short message asking for a "
            f"status update; cite the initiative by name. Do not call "
            f"schedule_followup."
        )
        out.append(
            NudgeCandidate(
                scope_key=f"{SCOPE_PREFIX_INITIATIVE}:{i.id}",
                intent_text=intent,
                source="initiative",
                urgency_seconds=(updated - now).total_seconds(),  # older = more urgent
                cooldown=cooldown,
                person_id=person_id,
                department=slug,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Channel routing
# ---------------------------------------------------------------------------

# The channel strings on scheduled_actions rows use slack_dm / discord_dm /
# telegram / email; the people.channel resolver returns slack / discord /
# telegram / email. This map bridges the gap.
_PEOPLE_TO_SCHEDULED_CHANNEL = {
    "slack": "slack_dm",
    "discord": "discord_dm",
    "telegram": "telegram",
    "email": "email",
}


def _to_scheduled_channel(people_channel: str) -> str | None:
    return _PEOPLE_TO_SCHEDULED_CHANNEL.get(people_channel)


def _route_candidate(
    candidate: NudgeCandidate,
    now: datetime,
    *,
    max_defer_days: int,
) -> _RoutedNudge | None:
    """Pick channel + delivery time for a candidate, or None if unroutable."""
    from openexecutive.people.channel import (
        next_available_window,
        prefer_channel_for,
    )

    if candidate.person_id is not None:
        pref = prefer_channel_for(candidate.person_id, now=now)
        if pref is not None:
            people_channel, channel_ref = pref
            sched = _to_scheduled_channel(people_channel)
            if sched is None:
                return None
            return _RoutedNudge(
                candidate=candidate,
                channel=sched,
                channel_ref=channel_ref,
                deliver_at=now,
            )
        # Person is currently unreachable — try to defer into their next
        # AVAILABLE slot. next_available_window only scans availability
        # windows and is blind to on_leave_until, so we must also clamp
        # the deferral to fall AFTER the leave end date — otherwise an
        # on-leave person with weekday 9-5 windows ends up in an infinite
        # defer→defer→defer loop until leave ends.
        nxt = next_available_window(candidate.person_id, after=now)
        leave_end = _leave_end_for(candidate.person_id)
        deliver_at = nxt
        if leave_end is not None and (deliver_at is None or deliver_at <= leave_end):
            deliver_at = leave_end
        if deliver_at is None or deliver_at > now + timedelta(days=max_defer_days):
            return None
        deferred = _static_channel_for_person(candidate.person_id)
        if deferred is None:
            return None
        people_channel, channel_ref = deferred
        sched = _to_scheduled_channel(people_channel)
        if sched is None:
            return None
        return _RoutedNudge(
            candidate=candidate,
            channel=sched,
            channel_ref=channel_ref,
            deliver_at=deliver_at,
        )

    # No person_id — only legal for the commitment source. Fall back to the
    # channel the original action was sent on.
    if candidate.fallback_channel and candidate.fallback_channel_ref:
        return _RoutedNudge(
            candidate=candidate,
            channel=candidate.fallback_channel,
            channel_ref=candidate.fallback_channel_ref,
            deliver_at=now,
        )
    return None


def _leave_end_for(person_id: int) -> datetime | None:
    """Return midnight UTC the day AFTER `on_leave_until`, or None.

    Used to clamp deferral targets so a nudge for an on-leave person
    isn't bounced back into the middle of their leave by an availability
    window check. Returns None when the person has no leave date set,
    can't be loaded, or is archived (archived skips earlier paths).
    """
    from datetime import time

    from openexecutive.people.registry import get_person

    person = get_person(person_id)
    if person is None or person.on_leave_until is None:
        return None
    return datetime.combine(
        person.on_leave_until + timedelta(days=1),
        time.min,
        tzinfo=UTC,
    )


def _static_channel_for_person(
    person_id: int,
) -> tuple[str, str] | None:
    """Return (people_channel, ref) ignoring availability windows.

    Used only when deferring into a future window — `prefer_channel_for`
    at the future time would re-evaluate windows and we already know we
    want the future delivery slot.
    """
    from openexecutive.people.channel import _resolve_channel
    from openexecutive.people.registry import get_person

    person = get_person(person_id)
    if person is None or person.archived:
        return None
    channel, ref = _resolve_channel(person)
    if not ref:
        return None
    return channel, ref


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

def _apply_caps(
    candidates: list[NudgeCandidate],
    *,
    max_total: int,
    max_per_person: int,
) -> list[NudgeCandidate]:
    """Sort by urgency, then truncate by per-person and global caps.

    `urgency_seconds` is ascending — smaller first (sooner deadline /
    older awaiting_response_since / older updated_at).
    """
    ranked = sorted(candidates, key=lambda c: c.urgency_seconds)
    per_person: dict[int, int] = defaultdict(int)
    accepted: list[NudgeCandidate] = []
    for c in ranked:
        if len(accepted) >= max_total:
            break
        if c.person_id is not None:
            if per_person[c.person_id] >= max_per_person:
                continue
            per_person[c.person_id] += 1
        accepted.append(c)
    return accepted


async def run_nudge_scan(
    now: datetime | None = None,
    *,
    db_path: Path | None = None,
) -> int:
    """One scan pass: collect → cap → dedup → route → insert. Returns count emitted."""
    from openexecutive.config import get_settings
    from openexecutive.memory.episodic import (
        insert_scheduled_action,
        recent_nudge_for_scope,
    )

    settings = get_settings()
    now = now or datetime.now(UTC)

    candidates: list[NudgeCandidate] = []
    try:
        candidates.extend(
            _select_stalled_workflow_candidates(
                now,
                lead_hours=settings.nudge_stalled_lead_hours,
                min_quiet_hours=settings.nudge_stalled_min_quiet_hours,
                cooldown_hours=settings.nudge_stalled_cooldown_hours,
                db_path=db_path,
            )
        )
    except Exception:
        logger.exception("nudge_engine: stalled-workflow source failed")
    try:
        candidates.extend(
            _select_stale_commitment_candidates(
                now,
                stale_days=settings.nudge_commitment_stale_days,
                cooldown_hours=settings.nudge_commitment_cooldown_hours,
                db_path=db_path,
            )
        )
    except Exception:
        logger.exception("nudge_engine: commitment source failed")
    try:
        candidates.extend(
            _select_idle_initiative_candidates(
                now,
                idle_days=settings.nudge_initiative_idle_days,
                cooldown_days=settings.nudge_initiative_cooldown_days,
                db_path=db_path,
            )
        )
    except Exception:
        logger.exception("nudge_engine: initiative source failed")

    if not candidates:
        return 0

    ranked = _apply_caps(
        candidates,
        max_total=settings.nudge_max_per_scan,
        max_per_person=settings.nudge_max_per_person_per_scan,
    )

    emitted = 0
    for cand in ranked:
        if recent_nudge_for_scope(
            cand.scope_key, now - cand.cooldown, db_path=db_path
        ):
            continue
        routed = _route_candidate(
            cand, now, max_defer_days=settings.nudge_max_defer_days
        )
        if routed is None:
            continue
        try:
            insert_scheduled_action(
                run_at=routed.deliver_at.isoformat(),
                channel=routed.channel,
                channel_ref=routed.channel_ref,
                intent_text=cand.intent_text,
                originating_session_id=cand.originating_session_id,
                # Department is left blank on the emitted nudge row so the
                # runner's authority gate doesn't propose/escalate it — the
                # nudge is about the approver, not a dept-scoped action.
                department="",
                kind="proactive_nudge",
                assigned_to_person_id=cand.person_id,
                scope_key=cand.scope_key,
                db_path=db_path,
            )
            emitted += 1
            logger.info(
                "nudge_engine: emitted %s (source=%s person=%s channel=%s "
                "deliver_at=%s)",
                cand.scope_key, cand.source, cand.person_id,
                routed.channel, routed.deliver_at.isoformat(),
            )
        except Exception:
            logger.exception(
                "nudge_engine: insert failed for scope %s", cand.scope_key
            )
    return emitted


# ---------------------------------------------------------------------------
# Heartbeat bootstrap / chain — mirrors departments/cadence.py
# ---------------------------------------------------------------------------

def _heartbeat_pending(db_path: Path | None = None) -> bool:
    from openexecutive.memory.episodic import _get_conn, _resolve_db_path

    resolved = _resolve_db_path(db_path)
    if not resolved.exists():
        return False
    with _get_conn(resolved) as conn:
        row = conn.execute(
            "SELECT 1 FROM scheduled_actions "
            "WHERE kind = ? AND status IN ('pending', 'running') LIMIT 1",
            (HEARTBEAT_KIND,),
        ).fetchone()
    return row is not None


def bootstrap_nudge_scan(db_path: Path | None = None) -> int | None:
    """Ensure exactly one pending nudge_scan row exists. Returns its id or None."""
    from openexecutive.config import get_settings
    from openexecutive.memory.episodic import insert_scheduled_action

    if _heartbeat_pending(db_path):
        return None
    settings = get_settings()
    run_at = datetime.now(UTC) + timedelta(minutes=settings.nudge_scan_interval_minutes)
    try:
        action_id = insert_scheduled_action(
            run_at=run_at.isoformat(),
            channel=HEARTBEAT_CHANNEL,
            channel_ref=HEARTBEAT_CHANNEL_REF,
            intent_text=HEARTBEAT_INTENT,
            kind=HEARTBEAT_KIND,
            db_path=db_path,
        )
        logger.info(
            "nudge_engine.bootstrap: heartbeat scheduled at %s (id=%d)",
            run_at.isoformat(), action_id,
        )
        return action_id
    except Exception:
        logger.exception("nudge_engine.bootstrap: failed to enqueue heartbeat")
        return None


def enqueue_next_scan(
    *,
    after: datetime | None = None,
    db_path: Path | None = None,
) -> int | None:
    """Schedule the next nudge_scan tick. Called by the runner after each fire."""
    from openexecutive.config import get_settings
    from openexecutive.memory.episodic import insert_scheduled_action

    settings = get_settings()
    base = (after or datetime.now(UTC)).astimezone(UTC)
    run_at = base + timedelta(minutes=settings.nudge_scan_interval_minutes)
    try:
        action_id = insert_scheduled_action(
            run_at=run_at.isoformat(),
            channel=HEARTBEAT_CHANNEL,
            channel_ref=HEARTBEAT_CHANNEL_REF,
            intent_text=HEARTBEAT_INTENT,
            kind=HEARTBEAT_KIND,
            db_path=db_path,
        )
        logger.info(
            "nudge_engine.enqueue_next: next scan at %s (id=%d)",
            run_at.isoformat(), action_id,
        )
        return action_id
    except Exception:
        logger.exception("nudge_engine.enqueue_next: insert failed")
        return None
