"""SQLite-backed persistence for the staff-onboarding framework.

Lives in the same ``episodic_memory.db`` as people / departments / talent /
episodic so there is one place to look. Tables are created idempotently via
``CREATE TABLE IF NOT EXISTS`` — no migration tooling needed.

The ``_resolve_db_path`` pattern lets tests monkeypatch ``DB_PATH`` and have it
take effect at call time, mirroring ``openexecutive.talent.store``.

Template task-specs and brief-section lists are stored as JSON text columns
(denormalized ``name`` / ``is_active`` alongside, like ``dynamic_workflows``);
plans and tasks are first-class rows so they can be queried and rolled up.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingPlan,
    OnboardingStatus,
    OnboardingTask,
    OnboardingTemplate,
    TaskSpec,
    TaskStatus,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("EPISODIC_DB_PATH", "./episodic_memory.db"))


def _resolve_db_path(db_path: Path | None) -> Path:
    """Return caller-supplied path or the current module-level DB_PATH.

    Dynamic resolution allows tests to monkeypatch DB_PATH and have it take
    effect at call time rather than at def time.
    """
    return db_path if db_path is not None else DB_PATH


@contextmanager
def _get_conn(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_resolve_db_path(db_path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

def initialize_db(db_path: Path | None = None) -> None:
    """Create staff-onboarding tables idempotently. Safe to call repeatedly."""
    with _get_conn(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS onboarding_templates (
                name TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                ramp_days INTEGER NOT NULL DEFAULT 0,
                checkin_cadence TEXT NOT NULL DEFAULT '',
                task_specs_json TEXT NOT NULL DEFAULT '[]',
                brief_sections_json TEXT NOT NULL DEFAULT '[]',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_onboarding_templates_active
                ON onboarding_templates(is_active);

            CREATE TABLE IF NOT EXISTS onboarding_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                person_id INTEGER,
                manager_person_id INTEGER,
                buddy_person_id INTEGER,
                template_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                current_phase TEXT NOT NULL DEFAULT 'pre_start',
                brief_artifact TEXT NOT NULL DEFAULT '',
                reading_list_json TEXT NOT NULL DEFAULT '[]',
                ramp_segments_json TEXT NOT NULL DEFAULT '[]',
                ramp_next_index INTEGER NOT NULL DEFAULT 0,
                engagement_id INTEGER,
                candidate_id INTEGER,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_onboarding_plans_status
                ON onboarding_plans(status);
            CREATE INDEX IF NOT EXISTS idx_onboarding_plans_person
                ON onboarding_plans(person_id);
            CREATE INDEX IF NOT EXISTS idx_onboarding_plans_archived
                ON onboarding_plans(archived);

            CREATE TABLE IF NOT EXISTS onboarding_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                phase TEXT NOT NULL DEFAULT 'week_1',
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                owner_person_id INTEGER,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                completed_at TEXT,
                completed_by_person_id INTEGER,
                notes TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES onboarding_plans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_onboarding_tasks_plan
                ON onboarding_tasks(plan_id);
        """)


# --------------------------------------------------------------------------- #
# Row mapping helpers
# --------------------------------------------------------------------------- #

def _row_to_template(row: sqlite3.Row) -> OnboardingTemplate:
    return OnboardingTemplate(
        name=row["name"],
        title=row["title"],
        description=row["description"],
        department=row["department"],
        ramp_days=int(row["ramp_days"]),
        checkin_cadence=row["checkin_cadence"],
        task_specs=[TaskSpec(**t) for t in json.loads(row["task_specs_json"] or "[]")],
        brief_sections=list(json.loads(row["brief_sections_json"] or "[]")),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_task(row: sqlite3.Row) -> OnboardingTask:
    return OnboardingTask(
        id=int(row["id"]),
        plan_id=int(row["plan_id"]),
        phase=OnboardingPhase(row["phase"]),
        title=row["title"],
        category=row["category"],
        owner_person_id=row["owner_person_id"],
        due_date=row["due_date"],
        status=TaskStatus(row["status"]),
        completed_at=row["completed_at"],
        completed_by_person_id=row["completed_by_person_id"],
        notes=row["notes"],
        sort_order=int(row["sort_order"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_plan(row: sqlite3.Row) -> OnboardingPlan:
    return OnboardingPlan(
        id=int(row["id"]),
        full_name=row["full_name"],
        role=row["role"],
        start_date=row["start_date"],
        person_id=row["person_id"],
        manager_person_id=row["manager_person_id"],
        buddy_person_id=row["buddy_person_id"],
        template_name=row["template_name"],
        status=OnboardingStatus(row["status"]),
        current_phase=OnboardingPhase(row["current_phase"]),
        brief_artifact=row["brief_artifact"],
        reading_list=list(json.loads(row["reading_list_json"] or "[]")),
        ramp_segments=list(json.loads(row["ramp_segments_json"] or "[]")),
        ramp_next_index=int(row["ramp_next_index"]),
        engagement_id=row["engagement_id"],
        candidate_id=row["candidate_id"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _completion_pct(statuses: list[TaskStatus]) -> int:
    """Percent of non-skipped tasks that are done (0 when there are none)."""
    counted = [s for s in statuses if s != TaskStatus.SKIPPED]
    if not counted:
        return 0
    done = sum(1 for s in counted if s == TaskStatus.DONE)
    return round(done * 100 / len(counted))


# --------------------------------------------------------------------------- #
# Template CRUD
# --------------------------------------------------------------------------- #

def upsert_template(template: OnboardingTemplate, db_path: Path | None = None) -> str:
    """Insert or replace a template by ``name``. Returns the template name.

    Stamps ``created_at`` on first insert and always refreshes ``updated_at``.
    """
    now = _now()
    task_specs_json = json.dumps([t.model_dump() for t in template.task_specs])
    brief_sections_json = json.dumps(list(template.brief_sections))
    with _get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT created_at FROM onboarding_templates WHERE name = ?",
            (template.name,),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            "INSERT OR REPLACE INTO onboarding_templates (name, title, description,"
            " department, ramp_days, checkin_cadence, task_specs_json,"
            " brief_sections_json, is_active, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                template.name, template.title, template.description,
                template.department, template.ramp_days, template.checkin_cadence,
                task_specs_json, brief_sections_json, int(template.is_active),
                created_at, now,
            ),
        )
    return template.name


def get_template(name: str, db_path: Path | None = None) -> OnboardingTemplate | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_templates"):
            return None
        row = conn.execute(
            "SELECT * FROM onboarding_templates WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_template(row) if row else None


def list_templates(
    active_only: bool = True, db_path: Path | None = None
) -> list[OnboardingTemplate]:
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_templates"):
            return []
        where = "WHERE is_active = 1" if active_only else ""
        rows = conn.execute(
            f"SELECT * FROM onboarding_templates {where} ORDER BY name"
        ).fetchall()
        return [_row_to_template(r) for r in rows]


def delete_template(name: str, db_path: Path | None = None) -> bool:
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM onboarding_templates WHERE name = ?", (name,)
        )
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Plan CRUD
# --------------------------------------------------------------------------- #

def create_plan(
    *,
    full_name: str,
    start_date: str,
    role: str = "",
    person_id: int | None = None,
    manager_person_id: int | None = None,
    buddy_person_id: int | None = None,
    template_name: str = "",
    status: OnboardingStatus = OnboardingStatus.DRAFT,
    engagement_id: int | None = None,
    candidate_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert a new onboarding plan. Returns the new plan id."""
    now = _now()
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO onboarding_plans (full_name, role, start_date, person_id,"
            " manager_person_id, buddy_person_id, template_name, status,"
            " current_phase, engagement_id, candidate_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                full_name, role, start_date, person_id, manager_person_id,
                buddy_person_id, template_name, status.value,
                OnboardingPhase.PRE_START.value, engagement_id, candidate_id,
                now, now,
            ),
        )
        return int(cursor.lastrowid or 0)


def get_plan(plan_id: int, db_path: Path | None = None) -> OnboardingPlan | None:
    """Fetch a plan with its tasks and computed ``completion_pct``."""
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_plans"):
            return None
        row = conn.execute(
            "SELECT * FROM onboarding_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        plan = _row_to_plan(row)
        task_rows = conn.execute(
            "SELECT * FROM onboarding_tasks WHERE plan_id = ? ORDER BY sort_order, id",
            (plan_id,),
        ).fetchall()
        plan.tasks = [_row_to_task(r) for r in task_rows]
        plan.completion_pct = _completion_pct([t.status for t in plan.tasks])
        return plan


def list_plans(
    status: OnboardingStatus | None = None,
    include_archived: bool = False,
    db_path: Path | None = None,
) -> list[OnboardingPlan]:
    """List plans (newest last) with ``completion_pct`` but without their tasks."""
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_plans"):
            return []
        clauses: list[str] = []
        params: list[object] = []
        if not include_archived:
            clauses.append("archived = 0")
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM onboarding_plans {where} ORDER BY id", params
        ).fetchall()
        plans = [_row_to_plan(r) for r in rows]
        # Roll completion up per plan in one extra query each — plan counts are
        # small (active hires), so this stays cheap.
        for plan in plans:
            task_rows = conn.execute(
                "SELECT status FROM onboarding_tasks WHERE plan_id = ?", (plan.id,)
            ).fetchall()
            plan.completion_pct = _completion_pct(
                [TaskStatus(r["status"]) for r in task_rows]
            )
        return plans


def update_plan(
    plan_id: int,
    *,
    person_id: int | None = None,
    manager_person_id: int | None = None,
    buddy_person_id: int | None = None,
    status: OnboardingStatus | None = None,
    current_phase: OnboardingPhase | None = None,
    brief_artifact: str | None = None,
    reading_list: list[str] | None = None,
    ramp_segments: list[str] | None = None,
    ramp_next_index: int | None = None,
    db_path: Path | None = None,
) -> bool:
    """Patch mutable plan fields. Only non-None args are written — this is a
    set-or-reassign helper, not a clear-to-NULL one (passing None for a
    person/manager/buddy leaves the existing value untouched; there is no flow
    that detaches those links). Returns True if a row was modified."""
    # (column, value) for each field the caller actually supplied.
    updates: list[tuple[str, object]] = []
    if person_id is not None:
        updates.append(("person_id", person_id))
    if manager_person_id is not None:
        updates.append(("manager_person_id", manager_person_id))
    if buddy_person_id is not None:
        updates.append(("buddy_person_id", buddy_person_id))
    if status is not None:
        updates.append(("status", status.value))
    if current_phase is not None:
        updates.append(("current_phase", current_phase.value))
    if brief_artifact is not None:
        updates.append(("brief_artifact", brief_artifact))
    if reading_list is not None:
        updates.append(("reading_list_json", json.dumps(list(reading_list))))
    if ramp_segments is not None:
        updates.append(("ramp_segments_json", json.dumps(list(ramp_segments))))
    if ramp_next_index is not None:
        updates.append(("ramp_next_index", ramp_next_index))
    if not updates:
        return False
    updates.append(("updated_at", _now()))
    sets = [f"{col} = ?" for col, _ in updates]
    params: list[object] = [val for _, val in updates]
    params.append(plan_id)
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE onboarding_plans SET {', '.join(sets)} WHERE id = ?", params
        )
        return cursor.rowcount > 0


def claim_next_ramp_segment(
    plan_id: int, db_path: Path | None = None
) -> tuple[str | None, bool]:
    """Pop the next ramp-drip segment for a plan and advance the index.

    Returns ``(segment_text, has_more)``. ``segment_text`` is None when the drip
    is exhausted (or the plan is missing) — the caller should not send anything
    and should not re-chain. ``has_more`` is True when at least one further
    segment remains after this one, so the scheduler knows whether to enqueue
    the next business-day occurrence.
    """
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT ramp_segments_json, ramp_next_index FROM onboarding_plans"
            " WHERE id = ? AND archived = 0",
            (plan_id,),
        ).fetchone()
        if row is None:
            return None, False
        segments = list(json.loads(row["ramp_segments_json"] or "[]"))
        idx = int(row["ramp_next_index"])
        if idx >= len(segments):
            return None, False
        segment = str(segments[idx])
        new_idx = idx + 1
        # Compare-and-swap on the index so two concurrent claims (a retry or a
        # double-fire) can't both serve the same segment: only the claim that
        # still sees ``idx`` wins; a loser sees rowcount 0 and serves nothing.
        cursor = conn.execute(
            "UPDATE onboarding_plans SET ramp_next_index = ?, updated_at = ?"
            " WHERE id = ? AND ramp_next_index = ?",
            (new_idx, _now(), plan_id, idx),
        )
        if cursor.rowcount == 0:
            return None, False
        return segment, new_idx < len(segments)


def archive_plan(plan_id: int, db_path: Path | None = None) -> bool:
    """Soft-delete a plan (and mark it archived). Returns True if found+archived."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE onboarding_plans SET archived = 1, status = ?, updated_at = ?"
            " WHERE id = ? AND archived = 0",
            (OnboardingStatus.ARCHIVED.value, _now(), plan_id),
        )
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Task CRUD
# --------------------------------------------------------------------------- #

def add_task(
    *,
    plan_id: int,
    title: str,
    phase: OnboardingPhase = OnboardingPhase.WEEK_1,
    category: str = "general",
    owner_person_id: int | None = None,
    due_date: str | None = None,
    sort_order: int = 0,
    db_path: Path | None = None,
) -> int:
    """Insert a task on a plan. Returns the new task id."""
    now = _now()
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO onboarding_tasks (plan_id, phase, title, category,"
            " owner_person_id, due_date, status, sort_order, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                plan_id, phase.value, title, category, owner_person_id, due_date,
                TaskStatus.PENDING.value, sort_order, now, now,
            ),
        )
        return int(cursor.lastrowid or 0)


def list_tasks(plan_id: int, db_path: Path | None = None) -> list[OnboardingTask]:
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_tasks"):
            return []
        rows = conn.execute(
            "SELECT * FROM onboarding_tasks WHERE plan_id = ? ORDER BY sort_order, id",
            (plan_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def get_task(task_id: int, db_path: Path | None = None) -> OnboardingTask | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "onboarding_tasks"):
            return None
        row = conn.execute(
            "SELECT * FROM onboarding_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None


def set_task_status(
    task_id: int,
    status: TaskStatus,
    *,
    completed_by_person_id: int | None = None,
    db_path: Path | None = None,
) -> bool:
    """Set a task's status. Moving to ``done`` stamps ``completed_at`` /
    ``completed_by_person_id``; moving away from ``done`` clears them. Returns
    True if a row was modified."""
    now = _now()
    completed_at = now if status == TaskStatus.DONE else None
    completed_by = completed_by_person_id if status == TaskStatus.DONE else None
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE onboarding_tasks SET status = ?, completed_at = ?,"
            " completed_by_person_id = ?, updated_at = ? WHERE id = ?",
            (status.value, completed_at, completed_by, now, task_id),
        )
        return cursor.rowcount > 0


def delete_task(task_id: int, db_path: Path | None = None) -> bool:
    with _get_conn(db_path) as conn:
        cursor = conn.execute("DELETE FROM onboarding_tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0
