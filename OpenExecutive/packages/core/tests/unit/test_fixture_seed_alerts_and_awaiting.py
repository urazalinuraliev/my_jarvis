"""``_seed_episodic_memory`` must seed the briefing's full surface from a
fixture ``memory.json``: the ``alerts`` table (Needs-you / Across-the-team /
Monitoring lanes) and ``scheduled_actions`` carrying ``awaiting_response_since``
(the In-flight / Awaiting lanes). It must also resolve *past* relative
sentinels (``-45m``, ``-30h``, ``-1d``) so overdue demo state is deterministic.

These guarantees back the halcyon/tandem demo fixtures, which rely on a single
``POST /fixtures/{name}/load`` to light up every section of the Today page.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from openexecutive.cli import fixture_loader
from openexecutive.cli.fixture_loader import (
    FIXTURES_ROOT,
    _resolve_run_at,
    _seed_episodic_memory,
)

# --------------------------------------------------------------------------- #
# _resolve_run_at: past offsets + day unit                                    #
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)


def test_resolve_run_at_negative_offsets() -> None:
    assert _resolve_run_at("-45m", NOW) == (NOW - timedelta(minutes=45)).isoformat()
    assert _resolve_run_at("-30h", NOW) == (NOW - timedelta(hours=30)).isoformat()
    assert _resolve_run_at("-45s", NOW) == (NOW - timedelta(seconds=45)).isoformat()


def test_resolve_run_at_day_unit() -> None:
    assert _resolve_run_at("+2d", NOW) == (NOW + timedelta(days=2)).isoformat()
    assert _resolve_run_at("-1d", NOW) == (NOW - timedelta(days=1)).isoformat()


def test_resolve_run_at_positive_still_works() -> None:
    # The sign-aware regex must not regress the original "+" behaviour.
    assert _resolve_run_at("+30s", NOW) == (NOW + timedelta(seconds=30)).isoformat()
    assert _resolve_run_at("+2h", NOW) == (NOW + timedelta(hours=2)).isoformat()


def test_resolve_run_at_invalid_still_none() -> None:
    assert _resolve_run_at("", NOW) is None
    assert _resolve_run_at("garbage", NOW) is None
    assert _resolve_run_at("-30", NOW) is None  # missing unit
    assert _resolve_run_at("-30x", NOW) is None  # invalid unit
    assert _resolve_run_at("+30y", NOW) is None  # invalid unit


# --------------------------------------------------------------------------- #
# Seeding: alerts + awaiting/in-flight scheduled actions                       #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def _episodic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp episodic DB with BOTH the episodic and alerts schemas.

    The fixture loader seeds alerts and scheduled_actions into the same
    physical DB, so the test DB must carry both schemas (the alerts tables
    are created by ``alerts.store.initialize_db``, not the episodic one).
    """
    from openexecutive.alerts import store as alerts_store
    from openexecutive.memory import episodic

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)
    alerts_store.initialize_db(db_path)
    return db_path


def _settings(db_path: Path) -> object:
    return type("S", (), {"episodic_db_path": db_path})()


def test_seed_alerts_routes_by_name_and_categorizes(
    tmp_path: Path, _episodic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A routed alert resolves its person id from the name cache and reads as
    an ``action`` proposal; an unrouted external signal reads as
    ``monitoring``.
    """
    from openexecutive.alerts.store import list_alerts
    from openexecutive.briefing.ranking import score_and_categorize

    monkeypatch.setattr(
        fixture_loader._seed_people,
        "_name_to_id",
        {"Jordan Avery": 42},
        raising=False,
    )

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "alerts": [
                    {
                        "external_id": "a-routed",
                        "source": "internal",
                        "severity": "high",
                        "routed_to_person": "Jordan Avery",
                        "headline": "Routed to the principal",
                        "body": "needs a decision",
                        "suggested_action": "approve",
                        "topic_tags": ["pricing"],
                        "created_at": "-2h",
                    },
                    {
                        "external_id": "a-monitoring",
                        "source": "stock",
                        "severity": "medium",
                        "headline": "Competitor stock dropped",
                        "body": "fyi only",
                        "topic_tags": ["external:stock-rivn"],
                        "created_at": "-5h",
                    },
                ],
            }
        )
    )

    counts = _seed_episodic_memory(memory_path, _settings(_episodic_db))
    assert counts["alerts"] == 2

    alerts = {a.external_id: a for a in list_alerts(status="unread", db_path=_episodic_db)}
    assert set(alerts) == {"a-routed", "a-monitoring"}

    routed = alerts["a-routed"]
    assert routed.routed_to_person_id == 42  # resolved from the name cache
    assert routed.created_at < datetime.now(UTC).isoformat()  # past sentinel resolved
    _, cat_routed, _ = score_and_categorize(routed)
    assert cat_routed == "action"

    mon = alerts["a-monitoring"]
    assert mon.routed_to_person_id is None
    _, cat_mon, _ = score_and_categorize(mon)
    assert cat_mon == "monitoring"


def test_seed_alerts_idempotent_on_reload(tmp_path: Path, _episodic_db: Path) -> None:
    """Re-running the seeder wipes and re-inserts — no accumulation."""
    from openexecutive.alerts.store import list_alerts

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "alerts": [
                    {
                        "external_id": "a1",
                        "source": "internal",
                        "severity": "high",
                        "headline": "one",
                        "body": "b",
                        "created_at": "-1h",
                    }
                ]
            }
        )
    )
    settings = _settings(_episodic_db)
    _seed_episodic_memory(memory_path, settings)
    _seed_episodic_memory(memory_path, settings)

    alerts = list_alerts(status="unread", db_path=_episodic_db)
    assert len(alerts) == 1


def test_seed_awaiting_and_in_flight(
    tmp_path: Path, _episodic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``awaiting_human`` row with a past ``awaiting_response_since`` lands in
    BOTH the in-flight list (overdue, since run_at is past) and the awaiting
    list; an ``__internal__`` scan stays out of in-flight.
    """
    from openexecutive.memory.episodic import (
        list_awaiting_replies_by_person,
        list_pending_scheduled_actions,
    )

    monkeypatch.setattr(
        fixture_loader._seed_people,
        "_name_to_id",
        {"Morgan Patel": 7},
        raising=False,
    )

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "scheduled_actions": [
                    {
                        "run_at": "+30s",
                        "kind": "watchlist_research_scan",
                        "channel": "__internal__",
                        "channel_ref": "watchlist_research",
                        "intent_text": "internal scan",
                    },
                    {
                        "run_at": "-2h",
                        "kind": "awaiting_human",
                        "channel": "discord_dm",
                        "channel_ref": "123",
                        "assigned_to_person": "Morgan Patel",
                        "department": "marketing",
                        "awaiting_response_since": "-30h",
                        "intent_text": "Awaiting Morgan's sign-off.",
                    },
                ],
            }
        )
    )
    counts = _seed_episodic_memory(memory_path, _settings(_episodic_db))
    assert counts["scheduled_actions"] == 2

    # In-flight excludes the internal scan; the awaiting_human row is overdue.
    pending = list_pending_scheduled_actions(db_path=_episodic_db)
    intents = [p.intent_text for p in pending]
    assert "Awaiting Morgan's sign-off." in intents
    assert "internal scan" not in intents
    banu_row = next(p for p in pending if p.assigned_to_person_id == 7)
    assert banu_row.awaiting_response_since is not None
    assert banu_row.run_at < datetime.now(UTC).isoformat()  # overdue

    # Awaiting groups by the assigned person, oldest in the past.
    awaiting = list_awaiting_replies_by_person(db_path=_episodic_db)
    assert 7 in awaiting
    count, oldest = awaiting[7]
    assert count == 1
    assert oldest is not None and oldest < datetime.now(UTC).isoformat()


def test_seed_scope_key_persists(tmp_path: Path, _episodic_db: Path) -> None:
    """``scope_key`` (used by the nudge engine for dedup) must round-trip."""
    import sqlite3

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "scheduled_actions": [
                    {
                        "run_at": "+6h",
                        "kind": "proactive_nudge",
                        "channel": "email",
                        "channel_ref": "x@example.com",
                        "scope_key": "nudge:demo:thing",
                        "intent_text": "nudge",
                    }
                ]
            }
        )
    )
    _seed_episodic_memory(memory_path, _settings(_episodic_db))
    conn = sqlite3.connect(str(_episodic_db))
    try:
        scope = conn.execute("SELECT scope_key FROM scheduled_actions").fetchone()[0]
    finally:
        conn.close()
    assert scope == "nudge:demo:thing"


def test_seed_alerts_noop_when_table_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DB without the alerts schema (legacy/partial) must not crash the
    seeder — alerts are skipped, scheduled_actions still seed.
    """
    from openexecutive.memory import episodic

    db_path = tmp_path / "episodic_no_alerts.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)  # episodic schema only — no alerts tables

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "alerts": [
                    {"external_id": "x", "source": "internal", "severity": "high",
                     "headline": "h", "body": "b", "created_at": "-1h"}
                ],
                "scheduled_actions": [
                    {"run_at": "+5s", "kind": "ad_hoc", "channel": "email",
                     "intent_text": "ok"}
                ],
            }
        )
    )
    counts = _seed_episodic_memory(memory_path, _settings(db_path))
    assert counts["alerts"] == 0
    assert counts["scheduled_actions"] == 1


# --------------------------------------------------------------------------- #
# Fixture integrity: routed/assigned names must exist; sentinels must resolve  #
# --------------------------------------------------------------------------- #

_DEMO_FIXTURES = ["halcyon_motors", "tandem_robotics", "meridian_petroleum"]


def _load_fixture(name: str) -> tuple[dict, set[str]]:
    fixture_dir = FIXTURES_ROOT / name
    memory = json.loads((fixture_dir / "memory.json").read_text())
    people = yaml.safe_load((fixture_dir / "people.yaml").read_text())
    names = {p["full_name"] for p in people["people"]}
    return memory, names


@pytest.mark.parametrize("name", _DEMO_FIXTURES)
def test_demo_fixture_names_and_sentinels_valid(name: str) -> None:
    memory, names = _load_fixture(name)
    now = datetime.now(UTC)

    # Every routed alert must name a real person, and every created_at must
    # be a resolvable sentinel or ISO string.
    for alert in memory.get("alerts", []):
        routed = alert.get("routed_to_person")
        if routed is not None:
            assert routed in names, f"{name}: alert routed to unknown person {routed!r}"
        if alert.get("created_at"):
            assert _resolve_run_at(alert["created_at"], now) is not None, (
                f"{name}: alert {alert.get('external_id')} bad created_at"
            )

    # Every assigned scheduled action must name a real person; run_at and any
    # awaiting_response_since must resolve.
    for sa in memory.get("scheduled_actions", []):
        assigned = sa.get("assigned_to_person")
        if assigned is not None:
            assert assigned in names, f"{name}: action assigned to unknown person {assigned!r}"
        assert _resolve_run_at(sa["run_at"], now) is not None, (
            f"{name}: action {sa.get('intent_text','')[:40]!r} bad run_at {sa['run_at']!r}"
        )
        if sa.get("awaiting_response_since"):
            assert _resolve_run_at(sa["awaiting_response_since"], now) is not None


@pytest.mark.parametrize("name", _DEMO_FIXTURES)
def test_demo_fixture_is_clean_baseline(name: str) -> None:
    """Each demo fixture must load to a CLEAN Today page: company *memory*
    (decisions / initiatives) is seeded, but no action lane is pre-populated.

    These fixtures are for running a real scenario from a clean baseline — the
    Today page should read "all clear" on load, and the only staged action is
    the ``+30s`` ``watchlist_research_scan`` that fires organically and proposes
    what to add to the watchlist. So: no pre-seeded ``alerts`` (Needs-you /
    Across-the-team / Monitoring lanes stay empty) and no non-``__internal__``
    ``scheduled_actions`` (In-flight / Awaiting stay empty).
    """
    memory, _ = _load_fixture(name)

    # Memory is still present — the Executive has context, just no open items.
    assert memory.get("decisions"), f"{name}: should seed decisions (memory)"
    assert memory.get("initiatives"), f"{name}: should seed initiatives (memory)"

    # No pre-baked alerts → no Needs-you / Across-the-team / Monitoring items.
    assert not memory.get("alerts"), (
        f"{name}: must not pre-seed alerts — the page should load clean and "
        f"build up organically from the research scan"
    )

    # The only staged action is the internal watchlist research scan.
    actions = memory.get("scheduled_actions", [])
    non_internal = [a for a in actions if a.get("channel") != "__internal__"]
    assert not non_internal, (
        f"{name}: must not pre-seed in-flight/awaiting actions — found "
        f"{[a.get('kind') for a in non_internal]}"
    )
    scans = [a for a in actions if a.get("kind") == "watchlist_research_scan"]
    assert len(scans) == 1, f"{name}: expected exactly one watchlist_research_scan"
    assert scans[0].get("channel") == "__internal__"


@pytest.mark.parametrize("name", _DEMO_FIXTURES)
def test_demo_fixture_actions_are_future_dated(name: str) -> None:
    """Safety contract: every non-``__internal__`` staged action must be
    FUTURE-dated. The scheduler claims any pending row with ``run_at <= now``
    (``episodic.claim_due_actions``— no kind filter) and dispatches
    it through the department gate, so a past-dated row would fire on load and
    could send a real message (fixtures use real emails/Discord IDs). The
    "overdue" briefing visual must instead come from a PAST
    ``awaiting_response_since`` on a future-dated row, which stays pending and
    is never claimed.
    """
    memory, _ = _load_fixture(name)
    for sa in memory.get("scheduled_actions", []):
        if sa.get("channel") == "__internal__":
            continue
        run_at = sa["run_at"]
        assert run_at.startswith("+"), (
            f"{name}: staged action {sa.get('intent_text','')[:50]!r} has a "
            f"non-future run_at {run_at!r} — would be claimed/dispatched on load"
        )
