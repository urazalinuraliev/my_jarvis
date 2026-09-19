"""SQLite-backed persistence for the talent / executive-search core.

Lives in the same ``episodic_memory.db`` as people / departments / episodic so
there is one place to look. Tables are created idempotently via
``CREATE TABLE IF NOT EXISTS`` — no migration tooling needed.

The ``_resolve_db_path`` pattern lets tests monkeypatch ``DB_PATH`` and have it
take effect at call time, mirroring ``openexecutive.people.store``.
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

from openexecutive.talent.models import (
    OPEN_OFFER_STATUSES,
    TERMINAL_OFFER_STATUSES,
    Candidate,
    CandidateStage,
    Engagement,
    EngagementStatus,
    Offer,
    OfferStatus,
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
    """Create talent tables idempotently. Safe to call repeatedly.

    One-time reset: the vertical moved from an external-client model (Client →
    Engagement → Candidate) to in-house hiring (Engagement → Candidate). There is
    no migration tooling, so if the legacy ``clients`` table is present we drop
    the three talent tables and rebuild them in the new shape. Only the talent
    tables are touched; the rest of ``episodic_memory.db`` is untouched.
    """
    with _get_conn(db_path) as conn:
        if _table_exists(conn, "clients"):
            # Legacy external-client schema detected — reset talent tables.
            logger.warning(
                "talent.store: legacy 'clients' schema found; dropping talent "
                "tables (clients/engagements/candidates) for the in-house model"
            )
            conn.executescript(
                "DROP TABLE IF EXISTS candidates;"
                "DROP TABLE IF EXISTS engagements;"
                "DROP TABLE IF EXISTS clients;"
            )
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS engagements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_title TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                location TEXT NOT NULL DEFAULT '',
                comp_band TEXT NOT NULL DEFAULT '',
                must_haves TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_engagements_archived ON engagements(archived);

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engagement_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                current_title TEXT NOT NULL DEFAULT '',
                current_company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                email TEXT,
                linkedin_url TEXT,
                source TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'lead',
                fit_score INTEGER,
                screening_summary TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (engagement_id) REFERENCES engagements(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_candidates_engagement ON candidates(engagement_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_stage ON candidates(stage);
            CREATE INDEX IF NOT EXISTS idx_candidates_archived ON candidates(archived);

            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                engagement_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                comp_summary TEXT NOT NULL DEFAULT '',
                package_md TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                expires_at TEXT,
                extended_at TEXT NOT NULL DEFAULT '',
                decided_at TEXT NOT NULL DEFAULT '',
                approval_run_id TEXT NOT NULL DEFAULT '',
                approved_by_person_id INTEGER,
                nudge_action_ids_json TEXT NOT NULL DEFAULT '[]',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
                FOREIGN KEY (engagement_id) REFERENCES engagements(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_offers_candidate ON offers(candidate_id);
            CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);
            CREATE INDEX IF NOT EXISTS idx_offers_archived ON offers(archived);
            -- DB-level backstop for the one-open-offer-per-candidate invariant:
            -- the SELECT guard in create_offer has a check-then-insert window,
            -- so concurrent creates settle here instead of producing two open
            -- offers.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_one_open
                ON offers(candidate_id)
                WHERE archived = 0
                  AND status IN ('draft', 'pending_approval', 'extended');
        """)


# --------------------------------------------------------------------------- #
# Row mapping helpers
# --------------------------------------------------------------------------- #

def _row_to_engagement(row: sqlite3.Row) -> Engagement:
    return Engagement(
        id=int(row["id"]),
        role_title=row["role_title"],
        department=row["department"],
        status=EngagementStatus(row["status"]),
        location=row["location"],
        comp_band=row["comp_band"],
        must_haves=row["must_haves"],
        description=row["description"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_candidate(row: sqlite3.Row) -> Candidate:
    return Candidate(
        id=int(row["id"]),
        engagement_id=int(row["engagement_id"]),
        full_name=row["full_name"],
        current_title=row["current_title"],
        current_company=row["current_company"],
        location=row["location"],
        email=row["email"],
        linkedin_url=row["linkedin_url"],
        source=row["source"],
        stage=CandidateStage(row["stage"]),
        fit_score=row["fit_score"],
        screening_summary=row["screening_summary"],
        notes=row["notes"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# --------------------------------------------------------------------------- #
# Engagement CRUD
# --------------------------------------------------------------------------- #

def upsert_engagement(
    *,
    role_title: str,
    department: str = "",
    status: EngagementStatus = EngagementStatus.OPEN,
    location: str = "",
    comp_band: str = "",
    must_haves: str = "",
    description: str = "",
    engagement_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert or update an engagement row. Returns the engagement_id."""
    now = _now()
    with _get_conn(db_path) as conn:
        if engagement_id is not None and engagement_id > 0:
            conn.execute(
                "UPDATE engagements SET role_title=?, department=?, status=?, location=?,"
                " comp_band=?, must_haves=?, description=?, updated_at=? WHERE id=?",
                (
                    role_title, department, status.value, location, comp_band,
                    must_haves, description, now, engagement_id,
                ),
            )
            return engagement_id
        cursor = conn.execute(
            "INSERT INTO engagements (role_title, department, status, location, comp_band,"
            " must_haves, description, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                role_title, department, status.value, location, comp_band,
                must_haves, description, now, now,
            ),
        )
        return int(cursor.lastrowid or 0)


def get_engagement(engagement_id: int, db_path: Path | None = None) -> Engagement | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "engagements"):
            return None
        row = conn.execute(
            "SELECT * FROM engagements WHERE id = ?", (engagement_id,)
        ).fetchone()
        return _row_to_engagement(row) if row else None


def list_engagements(
    include_archived: bool = False,
    db_path: Path | None = None,
) -> list[Engagement]:
    """List engagements (searches), newest id last."""
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "engagements"):
            return []
        where = "" if include_archived else "WHERE archived = 0"
        rows = conn.execute(
            f"SELECT * FROM engagements {where} ORDER BY id"
        ).fetchall()
        return [_row_to_engagement(r) for r in rows]


def set_engagement_status(
    engagement_id: int, status: EngagementStatus, db_path: Path | None = None
) -> bool:
    """Update an engagement's status. Returns True if a row was modified."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE engagements SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, _now(), engagement_id),
        )
        return cursor.rowcount > 0


def archive_engagement(engagement_id: int, db_path: Path | None = None) -> bool:
    """Soft-delete an engagement. Returns True if a row was found and archived."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE engagements SET archived = 1, updated_at = ? WHERE id = ? AND archived = 0",
            (_now(), engagement_id),
        )
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Candidate CRUD
# --------------------------------------------------------------------------- #

def upsert_candidate(
    *,
    engagement_id: int,
    full_name: str,
    current_title: str = "",
    current_company: str = "",
    location: str = "",
    email: str | None = None,
    linkedin_url: str | None = None,
    source: str = "",
    stage: CandidateStage = CandidateStage.LEAD,
    notes: str = "",
    candidate_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert or update a candidate row. Returns the candidate_id.

    ``fit_score`` and ``screening_summary`` are intentionally NOT settable
    here — they are owned by ``record_screening`` so a manual edit can never
    silently clobber a screen (or vice versa).
    """
    now = _now()
    with _get_conn(db_path) as conn:
        if candidate_id is not None and candidate_id > 0:
            conn.execute(
                "UPDATE candidates SET engagement_id=?, full_name=?, current_title=?,"
                " current_company=?, location=?, email=?, linkedin_url=?, source=?,"
                " stage=?, notes=?, updated_at=? WHERE id=?",
                (
                    engagement_id, full_name, current_title, current_company, location,
                    email, linkedin_url, source, stage.value, notes, now, candidate_id,
                ),
            )
            return candidate_id
        cursor = conn.execute(
            "INSERT INTO candidates (engagement_id, full_name, current_title,"
            " current_company, location, email, linkedin_url, source, stage, notes,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                engagement_id, full_name, current_title, current_company, location,
                email, linkedin_url, source, stage.value, notes, now, now,
            ),
        )
        return int(cursor.lastrowid or 0)


def get_candidate(candidate_id: int, db_path: Path | None = None) -> Candidate | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "candidates"):
            return None
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return _row_to_candidate(row) if row else None


def list_candidates(
    engagement_id: int | None = None,
    stage: CandidateStage | None = None,
    include_archived: bool = False,
    db_path: Path | None = None,
) -> list[Candidate]:
    """List candidates, optionally filtered by engagement and/or stage."""
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "candidates"):
            return []
        clauses: list[str] = []
        params: list[object] = []
        if not include_archived:
            clauses.append("archived = 0")
        if engagement_id is not None:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM candidates {where} ORDER BY id", params
        ).fetchall()
        return [_row_to_candidate(r) for r in rows]


def set_candidate_stage(
    candidate_id: int, stage: CandidateStage, db_path: Path | None = None
) -> bool:
    """Advance (or move) a candidate to a pipeline stage. Returns True on change."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE candidates SET stage = ?, updated_at = ? WHERE id = ?",
            (stage.value, _now(), candidate_id),
        )
        return cursor.rowcount > 0


def record_screening(
    candidate_id: int,
    *,
    fit_score: int,
    summary: str,
    advance_stage: bool = True,
    db_path: Path | None = None,
) -> bool:
    """Persist a screening result for a candidate.

    Stores ``fit_score`` (0-100) and the ``screening_summary``. When
    ``advance_stage`` is True (the default) and the candidate is still a raw
    ``lead``, moves them to ``screened`` — a screen that leaves the candidate a
    lead would be a no-op pipeline-wise. A candidate already past ``lead`` keeps
    their stage (re-screening shouldn't drag them backwards or skip them
    forward). Returns True if a row was modified.
    """
    if not 0 <= fit_score <= 100:
        raise ValueError(f"fit_score must be 0-100, got {fit_score}")
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT stage, archived FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        # Skip archived candidates: a long-running screen must not write a
        # score onto someone soft-deleted between fetch and persist.
        if row is None or row["archived"]:
            return False
        new_stage = row["stage"]
        if advance_stage and row["stage"] == CandidateStage.LEAD.value:
            new_stage = CandidateStage.SCREENED.value
        cursor = conn.execute(
            "UPDATE candidates SET fit_score = ?, screening_summary = ?, stage = ?,"
            " updated_at = ? WHERE id = ?",
            (fit_score, summary, new_stage, _now(), candidate_id),
        )
        return cursor.rowcount > 0


def archive_candidate(candidate_id: int, db_path: Path | None = None) -> bool:
    """Soft-delete a candidate. Returns True if a row was found and archived."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE candidates SET archived = 1, updated_at = ? WHERE id = ? AND archived = 0",
            (_now(), candidate_id),
        )
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Offers
# --------------------------------------------------------------------------- #

# Legal status transitions. Terminal statuses have no outgoing edges — a
# decided offer is history; re-offering means creating a new Offer row.
_OFFER_TRANSITIONS: dict[OfferStatus, frozenset[OfferStatus]] = {
    OfferStatus.DRAFT: frozenset(
        {OfferStatus.PENDING_APPROVAL, OfferStatus.EXTENDED, OfferStatus.RESCINDED}
    ),
    OfferStatus.PENDING_APPROVAL: frozenset(
        {OfferStatus.DRAFT, OfferStatus.EXTENDED, OfferStatus.RESCINDED}
    ),
    OfferStatus.EXTENDED: frozenset(
        {OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED, OfferStatus.RESCINDED}
    ),
    OfferStatus.ACCEPTED: frozenset(),
    OfferStatus.DECLINED: frozenset(),
    OfferStatus.EXPIRED: frozenset(),
    OfferStatus.RESCINDED: frozenset(),
}


def _row_to_offer(row: sqlite3.Row) -> Offer:
    try:
        nudge_ids = [int(x) for x in json.loads(row["nudge_action_ids_json"])]
    except (ValueError, TypeError):
        nudge_ids = []
    return Offer(
        id=int(row["id"]),
        candidate_id=int(row["candidate_id"]),
        engagement_id=int(row["engagement_id"]),
        status=OfferStatus(row["status"]),
        comp_summary=row["comp_summary"],
        package_md=row["package_md"],
        note=row["note"],
        expires_at=row["expires_at"],
        extended_at=row["extended_at"],
        decided_at=row["decided_at"],
        approval_run_id=row["approval_run_id"],
        approved_by_person_id=row["approved_by_person_id"],
        nudge_action_ids=nudge_ids,
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_offer(
    *,
    candidate_id: int,
    engagement_id: int,
    comp_summary: str = "",
    package_md: str = "",
    note: str = "",
    status: OfferStatus = OfferStatus.DRAFT,
    db_path: Path | None = None,
) -> int:
    """Insert an offer row. Returns the offer_id.

    Raises ``ValueError`` if the candidate already has an open offer
    (draft / pending_approval / extended) — one live offer per candidate —
    or if ``status`` is not an allowed insert state (only ``DRAFT`` and
    ``PENDING_APPROVAL``; an offer can't be born extended or decided).
    """
    if status not in (OfferStatus.DRAFT, OfferStatus.PENDING_APPROVAL):
        raise ValueError(f"offers can only be created as draft/pending_approval, got {status.value}")
    now = _now()
    with _get_conn(db_path) as conn:
        open_values = tuple(s.value for s in OPEN_OFFER_STATUSES)
        placeholders = ",".join("?" for _ in open_values)
        existing = conn.execute(
            f"SELECT id FROM offers WHERE candidate_id = ? AND archived = 0"
            f" AND status IN ({placeholders})",
            (candidate_id, *open_values),
        ).fetchone()
        if existing is not None:
            raise ValueError(
                f"candidate {candidate_id} already has an open offer (id {existing['id']})"
            )
        try:
            cursor = conn.execute(
                "INSERT INTO offers (candidate_id, engagement_id, status, comp_summary,"
                " package_md, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (candidate_id, engagement_id, status.value, comp_summary,
                 package_md, note, now, now),
            )
        except sqlite3.IntegrityError as exc:
            # Concurrent create slipped past the SELECT guard and hit the
            # idx_offers_one_open partial unique index.
            raise ValueError(
                f"candidate {candidate_id} already has an open offer"
            ) from exc
        return int(cursor.lastrowid or 0)


def get_offer(offer_id: int, db_path: Path | None = None) -> Offer | None:
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "offers"):
            return None
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        return _row_to_offer(row) if row else None


def get_open_offer_for_candidate(
    candidate_id: int, db_path: Path | None = None
) -> Offer | None:
    """Return the candidate's open offer (draft/pending_approval/extended), or None."""
    if not _resolve_db_path(db_path).exists():
        return None
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "offers"):
            return None
        open_values = tuple(s.value for s in OPEN_OFFER_STATUSES)
        placeholders = ",".join("?" for _ in open_values)
        row = conn.execute(
            f"SELECT * FROM offers WHERE candidate_id = ? AND archived = 0"
            f" AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            (candidate_id, *open_values),
        ).fetchone()
        return _row_to_offer(row) if row else None


def list_offers(
    candidate_id: int | None = None,
    engagement_id: int | None = None,
    status: OfferStatus | None = None,
    include_archived: bool = False,
    db_path: Path | None = None,
) -> list[Offer]:
    """List offers, optionally filtered by candidate, engagement, and/or status."""
    if not _resolve_db_path(db_path).exists():
        return []
    with _get_conn(db_path) as conn:
        if not _table_exists(conn, "offers"):
            return []
        clauses: list[str] = []
        params: list[object] = []
        if not include_archived:
            clauses.append("archived = 0")
        if candidate_id is not None:
            clauses.append("candidate_id = ?")
            params.append(candidate_id)
        if engagement_id is not None:
            clauses.append("engagement_id = ?")
            params.append(engagement_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(f"SELECT * FROM offers {where} ORDER BY id", params).fetchall()
        return [_row_to_offer(r) for r in rows]


def update_offer_terms(
    offer_id: int,
    *,
    comp_summary: str | None = None,
    package_md: str | None = None,
    note: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Update an offer's terms while it is still pre-extension.

    Only ``draft`` / ``pending_approval`` offers are editable — once an offer
    is extended (or decided) its terms are the record of what went out.
    Returns True if a row was modified.
    """
    fields: list[str] = []
    params: list[object] = []
    if comp_summary is not None:
        fields.append("comp_summary = ?")
        params.append(comp_summary)
    if package_md is not None:
        fields.append("package_md = ?")
        params.append(package_md)
    if note is not None:
        fields.append("note = ?")
        params.append(note)
    if not fields:
        return False
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE offers SET {', '.join(fields)}, updated_at = ?"
            " WHERE id = ? AND archived = 0 AND status IN (?, ?)",
            (*params, _now(), offer_id,
             OfferStatus.DRAFT.value, OfferStatus.PENDING_APPROVAL.value),
        )
        return cursor.rowcount > 0


def set_offer_status(
    offer_id: int,
    status: OfferStatus,
    *,
    expires_at: str | None = None,
    approval_run_id: str | None = None,
    approved_by_person_id: int | None = None,
    nudge_action_ids: list[int] | None = None,
    note: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Transition an offer to a new status, enforcing the lifecycle map.

    Stamps ``extended_at`` on → ``extended`` and ``decided_at`` on → any
    terminal status. Returns False (and logs) on an unknown offer or an
    illegal transition rather than raising — keeps tool/route error handling
    uniform with the rest of the store's boolean writes.
    """
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT status, archived FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if row is None or row["archived"]:
            return False
        current = OfferStatus(row["status"])
        if status not in _OFFER_TRANSITIONS[current]:
            logger.warning(
                "talent.store: illegal offer transition %s -> %s (offer %s)",
                current.value, status.value, offer_id,
            )
            return False
        now = _now()
        fields = ["status = ?", "updated_at = ?"]
        params: list[object] = [status.value, now]
        if status is OfferStatus.EXTENDED:
            fields.append("extended_at = ?")
            params.append(now)
        if status in TERMINAL_OFFER_STATUSES:
            fields.append("decided_at = ?")
            params.append(now)
        if expires_at is not None:
            fields.append("expires_at = ?")
            params.append(expires_at)
        if approval_run_id is not None:
            fields.append("approval_run_id = ?")
            params.append(approval_run_id)
        if approved_by_person_id is not None:
            fields.append("approved_by_person_id = ?")
            params.append(approved_by_person_id)
        if nudge_action_ids is not None:
            fields.append("nudge_action_ids_json = ?")
            params.append(json.dumps(nudge_action_ids))
        if note is not None:
            fields.append("note = ?")
            params.append(note)
        params.append(offer_id)
        cursor = conn.execute(
            f"UPDATE offers SET {', '.join(fields)} WHERE id = ?", params
        )
        return cursor.rowcount > 0


def archive_offer(offer_id: int, db_path: Path | None = None) -> bool:
    """Soft-delete an offer. Returns True if a row was found and archived."""
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE offers SET archived = 1, updated_at = ? WHERE id = ? AND archived = 0",
            (_now(), offer_id),
        )
        return cursor.rowcount > 0
