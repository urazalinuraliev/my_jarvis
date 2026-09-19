"""Regenerate OpenExecutive's builtin marketing skills from the ai-marketing-skills pack.

Run from packages/core:

    uv run python scripts/import_marketing_skills.py [--pack PATH]

--pack defaults to the ai-marketing-skills checkout next to OpenExecutive. The
skills are written to openexecutive/knowledge/builtin/skills/marketing/ and
the script prints what changed; see openexecutive.knowledge.agent_skills for
the conversion. Commit the result — the API indexes new builtin skills on its
next start.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openexecutive.knowledge.agent_skills import default_marketing_pack, import_pack
from openexecutive.knowledge.skills_index import BUILTIN_SKILLS_PATH

TARGET_DIR = BUILTIN_SKILLS_PATH / "marketing"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--pack",
        type=Path,
        default=default_marketing_pack(),
        help="ai-marketing-skills checkout (default: next to OpenExecutive)",
    )
    args = parser.parse_args()
    if not (args.pack / "skills").is_dir():
        print(f"No skills/ directory in {args.pack}", file=sys.stderr)
        return 1

    report = import_pack(args.pack, TARGET_DIR)
    for label, names in (
        ("written", report.written),
        ("unchanged", report.unchanged),
        ("removed", report.removed),
    ):
        print(f"{label:<9} {len(names):>2}  {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
