"""Background resumer loop — handles timeouts for WaitForHuman pauses.

Mirrors ``scheduler/runner.py``'s polling pattern.  Single-worker assumption:
do not run more than one resumer against the same database.

Phase 6 scope
-------------
* Timeout handling: when ``awaiting_until <= now``, apply the ``on_timeout``
  policy (escalate / auto_proceed / fail).
* ``apply_resolution``: called by integration hooks (Slack / Telegram / email)
  when a human replies. Stores the resolution, marks the run ``resolved``,
  and writes an audit entry.  Idempotent — a second call on the same run_id
  is a no-op (returns False).

Full generator resume (re-entering a paused async generator) is deferred to
Phase 7 — the complexity of serialising Python generator frames outweighs the
benefit for the initial ship.  ``resolved`` runs surface in the Today
dashboard so the founder can see the outcome.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import openexecutive.workflows.persistence as _wf_persistence
from openexecutive.workflows.wait_for_human import WaitForHumanResolution

logger = logging.getLogger(__name__)


async def apply_resolution(
    run_id: str,
    resolution: WaitForHumanResolution,
    db_path: Path | None = None,
) -> bool:
    """Persist a human resolution and mark the run resolved.

    Idempotent: if the run is already ``resolved`` (or not ``awaiting_human``),
    returns ``False`` without modifying any row.
    """
    from openexecutive.audit import log_event as audit_log

    resolution_dict = resolution.model_dump()
    resolution_dict["resolved_at"] = resolution.resolved_at or datetime.now(UTC).isoformat()
    resolution_json = json.dumps(resolution_dict)

    updated = _wf_persistence.store_resolution(run_id, resolution_json, db_path=db_path)
    if not updated:
        logger.info("resumer.apply_resolution: run %s not awaiting_human (no-op)", run_id)
        return False

    audit_log(
        "human_resolution",
        f"WaitForHuman resolved: run_id={run_id} person={resolution.person_id} "
        f"channel={resolution.source_channel} "
        f"decision={resolution.parsed_decision.get('decision', '?')}",
        actor=f"person:{resolution.person_id}",
        details={
            "run_id": run_id,
            "person_id": resolution.person_id,
            "source_channel": resolution.source_channel,
            "source_message_id": resolution.source_message_id,
            "reply_text": resolution.reply_text[:300],
            "parsed_decision": resolution.parsed_decision,
        },
    )
    logger.info(
        "resumer.apply_resolution: run %s resolved by person %d",
        run_id, resolution.person_id,
    )
    return True


async def _handle_timeout(run: dict, now: datetime) -> None:
    """Apply the timeout policy for an expired awaiting_human run."""

    import contextlib
    run_id = run["run_id"]
    state: dict = {}
    with contextlib.suppress(json.JSONDecodeError, TypeError):
        state = json.loads(run.get("state_json") or "{}")

    on_timeout = state.get("on_timeout", "escalate")
    person_id: int | None = run.get("awaiting_person_id")
    department = state.get("department", "")
    question = state.get("question", "")

    logger.info(
        "resumer: timeout for run_id=%s on_timeout=%s person=%s",
        run_id, on_timeout, person_id,
    )

    if on_timeout == "escalate":
        if department and person_id is not None:
            try:
                from openexecutive.departments.authority import propose_via_alert
                propose_via_alert(
                    department_slug=department,
                    person_id=person_id,
                    summary=f"[TIMEOUT] WaitForHuman expired: {question[:100]}",
                    body=(
                        f"Workflow run {run_id} timed out waiting for person {person_id}.\n\n"
                        f"Question: {question}\n\n"
                        f"Workflow: {run.get('workflow_name', '')} — {run.get('title', '')}"
                    ),
                    suggested_action=(
                        f"Resume the '{run.get('workflow_name', '')}' workflow — proceed "
                        "with a sensible default, or close it out if it's no longer needed."
                    ),
                )
            except Exception:
                logger.exception("resumer: escalation alert failed for run_id=%s", run_id)
        else:
            logger.warning(
                "resumer: escalate timeout for run_id=%s has no department/person — "
                "alert skipped, run marked timed_out",
                run_id,
            )
        _wf_persistence.mark_timed_out(run_id)

    elif on_timeout == "auto_proceed":
        auto_resolution = WaitForHumanResolution(
            run_id=run_id,
            reply_text="[auto-proceed on timeout]",
            source_channel="system",
            parsed_decision={"decision": "auto_proceed", "note": "timeout"},
            person_id=person_id or 0,
            resolved_at=now.isoformat(),
        )
        await apply_resolution(run_id, auto_resolution)

    else:  # "fail"
        _wf_persistence.fail_run(run_id, f"WaitForHuman timed out (on_timeout=fail) at {now.isoformat()}")


async def sweep_stale_awaiting(db_path: Path | None = None) -> int:
    """Apply the full on_timeout policy for all overdue ``awaiting_human`` rows.

    Called once at resumer startup to handle runs whose ``awaiting_until``
    fired while the server was down.  Mirrors ``_tick`` but runs eagerly before
    the first poll-sleep so the DB is consistent from the moment the resumer
    is live.

    The full ``_handle_timeout`` policy is applied (escalation alerts,
    auto-resolution, fail) — not merely a status flip — so no run silently
    loses its policy just because the server was restarted.

    Returns the count of runs processed.
    """
    now = datetime.now(UTC)
    runs = _wf_persistence.list_awaiting_runs(db_path=db_path)
    swept = 0
    for run in runs:
        raw_until = run.get("awaiting_until")
        if not raw_until:
            continue
        try:
            until_dt = datetime.fromisoformat(raw_until)
        except ValueError:
            logger.warning(
                "resumer.sweep: malformed awaiting_until %r for run_id=%s",
                raw_until, run.get("run_id"),
            )
            continue
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=UTC)
        if until_dt <= now:
            try:
                await _handle_timeout(run, now)
                swept += 1
                logger.info(
                    "resumer.sweep: applied timeout policy for run_id=%s (awaiting_until=%s)",
                    run["run_id"], raw_until,
                )
            except Exception:
                logger.exception(
                    "resumer.sweep: _handle_timeout failed for run_id=%s", run.get("run_id")
                )
    if swept:
        logger.info("resumer.sweep: %d stale awaiting_human run(s) processed at startup", swept)
    return swept


async def run_resumer(poll_interval_seconds: int = 60) -> None:
    """Poll for timed-out awaiting_human runs and apply timeout policies.

    Mirrors ``scheduler/runner.run_scheduler`` — same single-worker assumption,
    same asyncio-sleep polling pattern.

    An async startup sweep runs first to apply the full on_timeout policy for
    any runs that expired while the server was down, before the first tick.
    """
    logger.info("resumer started (poll_interval=%ds)", poll_interval_seconds)
    swept = await sweep_stale_awaiting()
    if swept:
        logger.info("resumer: startup sweep processed %d stale run(s)", swept)
    while True:
        try:
            now = datetime.now(UTC)
            await _tick(now)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("resumer tick failed")
        try:
            await asyncio.sleep(poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("resumer cancelled — exiting")
            raise


async def _tick(now: datetime) -> None:
    """Process one poll cycle — handle all timed-out runs."""
    runs = _wf_persistence.list_awaiting_runs()
    timed_out = []
    for r in runs:
        raw_until = r.get("awaiting_until")
        if not raw_until:
            continue
        try:
            until_dt = datetime.fromisoformat(raw_until)
            # Always compare timezone-aware datetimes. Stored timestamps
            # may lack tz info (naive) if saved with a naive datetime; treat
            # those as UTC to avoid silent early-expiry on naive inputs.
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=UTC)
            if until_dt <= now:
                timed_out.append(r)
        except ValueError:
            logger.warning("resumer: malformed awaiting_until %r for run_id=%s", raw_until, r.get("run_id"))
    if timed_out:
        logger.info("resumer: %d timed-out run(s)", len(timed_out))
    for run in timed_out:
        try:
            await _handle_timeout(run, now)
        except Exception:
            logger.exception("resumer: _handle_timeout failed for run_id=%s", run.get("run_id"))
