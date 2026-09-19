"""Phase 8 hardening tests.

Covers:
1. Dedup namespacing — proposals to different people never collide.
2. Resumer startup sweep — stale awaiting_human rows transitioned on start.
3. Org completeness check — warnings for missing heads and scopes.
4. Head persona override — placeholder created on first seed, idempotent.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.agents import overrides as agent_overrides
from openexecutive.alerts import store as alert_store
from openexecutive.departments import registry as dept_registry
from openexecutive.departments import store as dept_store
from openexecutive.departments.completeness import check_org_completeness
from openexecutive.departments.head_persona import ensure_head_persona_override
from openexecutive.memory import episodic
from openexecutive.people import registry as people_registry
from openexecutive.people import store as people_store
from openexecutive.people.models import AuthorityScope
from openexecutive.workflows import persistence as wf_persistence
from openexecutive.workflows.resumer import sweep_stale_awaiting


# ---------------------------------------------------------------------------
# Shared isolation fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setattr(episodic, "DB_PATH", db)
    monkeypatch.setattr(dept_store, "DB_PATH", db)
    monkeypatch.setattr(people_store, "DB_PATH", db)
    monkeypatch.setattr(alert_store, "DB_PATH", db)
    monkeypatch.setattr(wf_persistence, "DB_PATH", db)
    monkeypatch.setattr(agent_overrides, "DB_PATH", db)
    dept_registry.invalidate()
    people_registry.invalidate()
    agent_overrides.invalidate_cache()

    episodic.initialize_db(db)
    dept_store.initialize_db(db)
    people_store.initialize_db(db)
    alert_store.initialize_db(db)
    wf_persistence.initialize_runs_db(db)
    agent_overrides.initialize_overrides_db(db)
    dept_store.seed_default_departments(db_path=db)
    yield
    dept_registry.invalidate()
    people_registry.invalidate()
    agent_overrides.invalidate_cache()


# ---------------------------------------------------------------------------
# 1. Dedup namespacing
# ---------------------------------------------------------------------------

class TestDedupNamespacing:
    """Proposals to DIFFERENT people must not be suppressed as duplicates.
    Proposals to the SAME person with the SAME summary MUST be suppressed.
    """

    def test_same_person_same_summary_is_deduplicated(self) -> None:
        from openexecutive.departments.authority import propose_via_alert

        pid = people_store.upsert_person(full_name="Alice", role="CFO")
        first = propose_via_alert("finance", pid, "Approve vendor contract", "body")
        assert first is not None
        second = propose_via_alert("finance", pid, "Approve vendor contract", "body")
        assert second is None, "Same person + same summary must be deduplicated"

    def test_different_people_same_summary_not_deduplicated(self) -> None:
        """Person A and Person B both receive their own copy of the same proposal."""
        from openexecutive.departments.authority import propose_via_alert

        alice_id = people_store.upsert_person(full_name="Alice", role="CFO")
        bob_id = people_store.upsert_person(full_name="Bob", role="COO")

        alice_alert = propose_via_alert("finance", alice_id, "Approve vendor contract", "body")
        bob_alert = propose_via_alert("finance", bob_id, "Approve vendor contract", "body")

        assert alice_alert is not None, "Alice should receive her proposal"
        assert bob_alert is not None, "Bob should receive his proposal — different person, no collision"
        assert alice_alert != bob_alert, "Different alert IDs for different people"

        # Verify topic_tags route each alert to the right person
        alice_rec = alert_store.get_alert(alice_alert)
        bob_rec = alert_store.get_alert(bob_alert)
        assert alice_rec is not None and bob_rec is not None
        assert f"person:{alice_id}" in alice_rec.topic_tags
        assert f"person:{bob_id}" in bob_rec.topic_tags
        assert alice_rec.routed_to_person_id == alice_id
        assert bob_rec.routed_to_person_id == bob_id

    def test_different_departments_same_person_same_summary_not_deduplicated(self) -> None:
        """Finance and HR can both propose the same action to the same person."""
        from openexecutive.departments.authority import propose_via_alert

        pid = people_store.upsert_person(full_name="Principal", role="CEO", is_principal=True)

        finance_alert = propose_via_alert("finance", pid, "Budget review", "body")
        hr_alert = propose_via_alert("hr_talent", pid, "Budget review", "body")

        assert finance_alert is not None
        assert hr_alert is not None
        assert finance_alert != hr_alert


# ---------------------------------------------------------------------------
# 2. Resumer startup sweep
# ---------------------------------------------------------------------------

def _seed_awaiting(
    run_id: str,
    person_id: int,
    awaiting_until: datetime,
    db_path: Path | None = None,
) -> None:
    wf_persistence.create_run(run_id, "test_wf", "Test", {}, db_path=db_path)
    state = json.dumps({"on_timeout": "fail", "channel": "slack"})
    wf_persistence.save_checkpoint(run_id, state, person_id, awaiting_until, db_path=db_path)


class TestStartupSweep:
    def test_sweep_applies_policy_for_expired_runs(self) -> None:
        """Stale runs get full on_timeout=fail policy applied (status → error)."""
        past = datetime.now(UTC) - timedelta(hours=2)
        pid = people_store.upsert_person(full_name="Bob")
        _seed_awaiting("stale-run", pid, past)

        swept = asyncio.run(sweep_stale_awaiting())
        assert swept == 1
        # on_timeout="fail" → status should be "error" (full policy, not just timed_out)
        assert wf_persistence.get_run("stale-run")["status"] == "error"

    def test_sweep_ignores_future_runs(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=24)
        pid = people_store.upsert_person(full_name="Carol")
        _seed_awaiting("future-run", pid, future)

        swept = asyncio.run(sweep_stale_awaiting())
        assert swept == 0
        assert wf_persistence.get_run("future-run")["status"] == "awaiting_human"

    def test_sweep_skips_run_with_no_awaiting_until(self) -> None:
        """Runs without a deadline must never be touched."""
        pid = people_store.upsert_person(full_name="Frank")
        wf_persistence.create_run("no-until", "wf", "Test", {})
        state = json.dumps({"on_timeout": "fail", "channel": "slack"})
        wf_persistence.save_checkpoint("no-until", state, pid, None)

        swept = asyncio.run(sweep_stale_awaiting())
        assert swept == 0
        assert wf_persistence.get_run("no-until")["status"] == "awaiting_human"

    def test_sweep_is_idempotent(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        pid = people_store.upsert_person(full_name="Dave")
        _seed_awaiting("dup-run", pid, past)

        first = asyncio.run(sweep_stale_awaiting())
        second = asyncio.run(sweep_stale_awaiting())
        assert first == 1
        assert second == 0  # run no longer awaiting_human — not picked up again

    def test_sweep_only_touches_awaiting_human_status(self) -> None:
        """Already-resolved runs must not be touched by the sweep."""
        pid = people_store.upsert_person(full_name="Eve")
        past = datetime.now(UTC) - timedelta(hours=1)

        _seed_awaiting("resolved-run", pid, past)
        wf_persistence.store_resolution("resolved-run", '{"decision":"approve"}')

        swept = asyncio.run(sweep_stale_awaiting())
        assert swept == 0
        assert wf_persistence.get_run("resolved-run")["status"] == "resolved"

    def test_run_resumer_awaits_sweep_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_resumer must await sweep_stale_awaiting before entering the poll loop."""
        swept_calls: list[int] = []

        original_sweep = sweep_stale_awaiting

        async def mock_sweep(db_path: Path | None = None) -> int:
            result = await original_sweep(db_path=db_path)
            swept_calls.append(result)
            return result

        monkeypatch.setattr(
            "openexecutive.workflows.resumer.sweep_stale_awaiting", mock_sweep
        )

        # Seed a stale run so we can verify the sweep actually did work
        pid = people_store.upsert_person(full_name="Grace")
        past = datetime.now(UTC) - timedelta(hours=1)
        _seed_awaiting("startup-stale", pid, past)

        from openexecutive.workflows.resumer import run_resumer

        async def _run_briefly() -> None:
            task = asyncio.create_task(run_resumer(poll_interval_seconds=60))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run_briefly())
        assert len(swept_calls) >= 1, "sweep_stale_awaiting must be awaited at startup"
        assert swept_calls[0] >= 1, "sweep must have processed the seeded stale run"


# ---------------------------------------------------------------------------
# 3. Org completeness check
# ---------------------------------------------------------------------------

class TestOrgCompleteness:
    def test_warns_when_department_has_no_head(self) -> None:
        # By default, seeded departments have no head_person_id
        warnings = check_org_completeness()
        dept_warnings = [w for w in warnings if "has no head person" in w]
        assert len(dept_warnings) == 8, f"All 8 default departments should warn: {dept_warnings}"
        assert any("Finance" in w for w in dept_warnings)

    def test_no_head_warning_after_head_is_set(self) -> None:
        pid = people_store.upsert_person(full_name="Sarah Chen", role="CFO")
        dept_store.update_department("finance", head_person_id=pid)
        warnings = check_org_completeness()
        finance_head_warnings = [w for w in warnings if "Finance" in w and "head person" in w]
        assert len(finance_head_warnings) == 0

    def test_warns_when_scope_has_no_non_principal_approver(self) -> None:
        # No people seeded — every scope should warn
        warnings = check_org_completeness()
        scope_warnings = [w for w in warnings if "No non-principal approver" in w]
        # Should have one warning per non-WILDCARD scope (8 scopes)
        non_wc_count = sum(1 for s in AuthorityScope if s != AuthorityScope.WILDCARD)
        assert len(scope_warnings) == non_wc_count

    def test_no_scope_warning_after_approver_configured(self) -> None:
        cfo_id = people_store.upsert_person(full_name="Sarah Chen", is_principal=False)
        people_store.set_authority_scope(cfo_id, [AuthorityScope.SPEND_GT_10K])
        warnings = check_org_completeness()
        spend_gt_10k_warnings = [
            w for w in warnings if "spend_gt_10k" in w
        ]
        assert len(spend_gt_10k_warnings) == 0

    def test_principal_with_wildcard_does_not_suppress_scope_warning(self) -> None:
        """A principal with WILDCARD is a fallback, not a non-principal approver.
        The completeness check should still warn that no human expert is configured."""
        principal_id = people_store.upsert_person(full_name="Founder", is_principal=True)
        people_store.set_authority_scope(principal_id, [AuthorityScope.WILDCARD])
        warnings = check_org_completeness()
        scope_warnings = [w for w in warnings if "No non-principal approver" in w]
        non_wc_count = sum(1 for s in AuthorityScope if s != AuthorityScope.WILDCARD)
        assert len(scope_warnings) == non_wc_count

    def test_returns_empty_when_fully_configured(self) -> None:
        """After setting a head for every dept and a non-principal for each scope,
        no warnings should remain."""
        # Create a person to cover all scopes
        pid = people_store.upsert_person(full_name="Jane", is_principal=False)
        people_store.set_authority_scope(
            pid,
            [s for s in AuthorityScope if s != AuthorityScope.WILDCARD],
        )
        # Set as head for every department
        for ds in dept_store.list_departments():
            dept_store.update_department(ds.config.slug, head_person_id=pid)
        dept_registry.invalidate()

        warnings = check_org_completeness()
        assert warnings == [], f"Expected no warnings, got: {warnings}"


# ---------------------------------------------------------------------------
# 4. Head persona override
# ---------------------------------------------------------------------------

class TestHeadPersonaOverride:
    def test_creates_placeholder_override(self, tmp_path: Path) -> None:
        db = tmp_path / "hp.db"
        agent_overrides.initialize_overrides_db(db_path=db)
        agent_overrides.invalidate_cache()

        created = ensure_head_persona_override("finance", person_id=42, db_path=db)
        assert created is True

        override = agent_overrides.get_override("department:finance:head", db_path=db)
        assert override is not None
        assert override.role is not None and "finance" in override.role.lower()
        # Prompt stays None — voice-only placeholder
        assert override.prompt is None

    def test_idempotent_does_not_overwrite(self, tmp_path: Path) -> None:
        db = tmp_path / "hp2.db"
        agent_overrides.initialize_overrides_db(db_path=db)
        agent_overrides.invalidate_cache()

        first = ensure_head_persona_override("finance", person_id=42, db_path=db)
        assert first is True

        # Manually customise the override
        agent_overrides.set_override(
            "department:finance:head",
            prompt="Speak like a seasoned CFO.",
            prompt_set=True,
            db_path=db,
        )
        agent_overrides.invalidate_cache()

        second = ensure_head_persona_override("finance", person_id=99, db_path=db)
        assert second is False  # already exists — must not overwrite

        override = agent_overrides.get_override("department:finance:head", db_path=db)
        assert override is not None
        assert override.prompt == "Speak like a seasoned CFO."  # operator text preserved
