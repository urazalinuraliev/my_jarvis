#!/usr/bin/env python3
"""Wipe every row from the local episodic memory database.

Standalone developer tool. Deliberately lives outside the `openexecutive`
package so the running app process cannot import it — only a human at a
terminal can run this.

Usage:
    python scripts/clear_memory.py            # prompts for confirmation
    python scripts/clear_memory.py --yes      # skip the prompt
    python scripts/clear_memory.py --db PATH  # target a non-default DB file
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Mirrors `openexecutive.memory.episodic.DB_PATH` and the table set defined
# across `memory/episodic.py`, `memory/session_store.py`, `alerts/store.py`,
# `knowledge/review_schema.py`, and `workflows/persistence.py`. Kept in sync by
# hand — this script intentionally does not import the package.
DEFAULT_DB_PATH = Path("./episodic_memory.db")

TABLES: tuple[str, ...] = (
    "chat_messages",
    "sessions",
    "decisions",
    "initiatives",
    "advice_given",
)


def clear(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return dict.fromkeys(TABLES, 0)
    counts: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for table in TABLES:
            try:
                cursor = conn.execute(f"DELETE FROM {table}")
                counts[table] = cursor.rowcount
            except sqlite3.OperationalError as exc:
                # Table doesn't exist yet — DB initialised on first API run.
                counts[table] = 0
                print(f"  (skipped {table}: {exc})", file=sys.stderr)
        conn.commit()
    finally:
        conn.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite file to clear (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    db_path: Path = args.db.resolve()

    if not db_path.exists():
        print(f"No episodic database at {db_path} — nothing to clear.")
        return 0

    if not args.yes:
        print(f"This will delete ALL memory rows from {db_path}.")
        reply = input("Type 'clear' to confirm: ").strip().lower()
        if reply != "clear":
            print("Cancelled.")
            return 1

    counts = clear(db_path)
    total = sum(counts.values())
    print(f"Cleared {total} rows from {db_path}:")
    for table, n in counts.items():
        print(f"  - {table}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
