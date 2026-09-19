"""ChromaDB integration for the skills library.

Each skill is one document (no chunking — frontmatter + 100s of words fit easily).
The search corpus is the concatenation of name, description, and when_to_use;
the body is fetched separately via `load_skill`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openexecutive.knowledge.loader import BUILTIN_KNOWLEDGE_PATH
from openexecutive.knowledge.skills import (
    Skill,
    SkillSource,
    parse_skill_file,
)
from openexecutive.knowledge.store import ChromaDBStore

logger = logging.getLogger(__name__)

SKILLS_COLLECTION = "skills"
BUILTIN_SKILLS_PATH = BUILTIN_KNOWLEDGE_PATH / "skills"


def _company_skills_path() -> Path:
    from openexecutive.config import get_settings

    return get_settings().company_profile_path.parent / "skills"


def _skill_id(name: str, source: SkillSource) -> str:
    return f"skill::{source}::{name}"


def _skill_doc_text(skill: Skill) -> str:
    fm = skill.frontmatter
    return f"{fm.name}\n{fm.description}\n{fm.when_to_use}"


def index_skill(skill: Skill, store: ChromaDBStore) -> None:
    """Upsert a single skill into the skills collection. Idempotent."""
    fm = skill.frontmatter
    store.add_documents(
        texts=[_skill_doc_text(skill)],
        metadatas=[{
            "name": fm.name,
            "category": fm.category,
            "source": skill.source,
            "description": fm.description,
            "when_to_use": fm.when_to_use,
            "filename": Path(skill.path).name,
            "path": skill.path,
        }],
        ids=[_skill_id(fm.name, skill.source)],
        collection=SKILLS_COLLECTION,
    )


def delete_skill_index(name: str, source: SkillSource, store: ChromaDBStore) -> None:
    """Remove a single skill row from the index."""
    store.delete_documents(
        collection=SKILLS_COLLECTION,
        where={"$and": [{"name": name}, {"source": source}]},
    )


def search_skills(
    query: str,
    store: ChromaDBStore,
    n_results: int = 5,
    source_filter: SkillSource | None = None,
) -> list[dict[str, Any]]:
    """Semantic search across the skill index.

    Returns a list of `{name, category, description, when_to_use, source, score}`
    — no body. The Executive must call `load_skill` to fetch the procedure.
    """
    if n_results <= 0:
        return []

    col = store._get_or_create_collection(SKILLS_COLLECTION)
    count = col.count()
    if count == 0:
        return []

    where: dict[str, Any] | None = {"source": source_filter} if source_filter else None
    query_kwargs: dict[str, Any] = {
        "query_texts": [query],
        "n_results": min(n_results, count),
        "include": ["metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    results = col.query(**query_kwargs)
    hits: list[dict[str, Any]] = []
    if results["metadatas"] and results["metadatas"][0]:
        for meta, dist in zip(
            results["metadatas"][0],
            results["distances"][0],
            strict=False,
        ):
            # Cosine distance -> similarity score for human readability.
            score = max(0.0, 1.0 - float(dist))
            hits.append({
                "name": meta.get("name", ""),
                "category": meta.get("category", ""),
                "description": meta.get("description", ""),
                "when_to_use": meta.get("when_to_use", ""),
                "source": meta.get("source", ""),
                "score": round(score, 4),
            })
    return hits


def _indexed_builtin_skills(store: ChromaDBStore) -> dict[str, dict[str, Any]]:
    """The builtin rows of the skill index: id → metadata."""
    col = store._get_or_create_collection(SKILLS_COLLECTION)
    rows = col.get(where={"source": "builtin"}, include=["metadatas"])
    return dict(zip(rows.get("ids", []), rows.get("metadatas") or [], strict=False))


def _index_is_current(meta: dict[str, Any] | None, skill: Skill) -> bool:
    """Whether an indexed row still matches the text it embeds (see _skill_doc_text)."""
    fm = skill.frontmatter
    return meta is not None and (
        meta.get("description"),
        meta.get("when_to_use"),
        meta.get("category"),
    ) == (fm.description, fm.when_to_use, fm.category)


def _iter_skill_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.md"))


async def seed_builtin_skills(store: ChromaDBStore | None = None, force: bool = False) -> int:
    """Bring the index's builtin rows in line with the builtin skills on disk.

    Indexes builtin skills that are new or whose description, when_to_use or
    category changed (e.g. after a pack re-import), drops rows whose file is
    gone, and leaves the rest alone, so start-up only embeds what changed.
    ``force`` re-indexes every builtin skill. Returns how many were indexed.
    """
    if store is None:
        from openexecutive.config import get_settings

        store = ChromaDBStore(persist_directory=get_settings().vector_store_path)

    indexed = _indexed_builtin_skills(store)
    on_disk: set[str] = set()
    count = 0
    for path in _iter_skill_files(BUILTIN_SKILLS_PATH):
        try:
            skill = parse_skill_file(path, source="builtin")
        except (ValueError, TypeError, OSError) as e:
            # SkillParseError is a ValueError; the rest come from a file that is
            # unreadable or undecodable, or has a non-string field. This runs on
            # every start, so one bad file must not abort the seeding after it.
            logger.warning("Skipping malformed skill %s: %s", path, e)
            continue
        skill_id = _skill_id(skill.frontmatter.name, "builtin")
        on_disk.add(skill_id)
        if not force and _index_is_current(indexed.get(skill_id), skill):
            continue
        index_skill(skill, store)
        count += 1

    if on_disk:
        for skill_id, meta in indexed.items():
            if skill_id not in on_disk:
                delete_skill_index(str(meta.get("name", "")), "builtin", store)
    elif indexed:
        # No readable builtin skill at all is a broken install, not a release
        # that dropped them all: keep the rows rather than wipe the index.
        logger.warning(
            "No builtin skills found under %s; keeping the %d indexed ones",
            BUILTIN_SKILLS_PATH,
            len(indexed),
        )
    _warn_about_shadowed_company_skills()
    return count


def _warn_about_shadowed_company_skills() -> None:
    """Log company skills hidden by a builtin skill of the same name.

    Name lookups (load_skill, update, delete) resolve builtin first, so such a
    company skill is unreachable until renamed. New company skills can't take
    a builtin name; this catches ones created before that builtin shipped.
    """
    builtin = {path.stem for path in _iter_skill_files(BUILTIN_SKILLS_PATH)}
    for path in _iter_skill_files(_company_skills_path()):
        if path.stem in builtin:
            logger.warning(
                "Company skill %s is shadowed by the builtin skill of the same name; "
                "rename it to use it again",
                path,
            )


def count_skills(store: ChromaDBStore, source: SkillSource | None = None) -> int:
    """Count indexed skills, optionally filtered by source."""
    col = store._get_or_create_collection(SKILLS_COLLECTION)
    if source is None:
        return col.count()
    try:
        result = col.get(where={"source": source}, include=[])
        return len(result.get("ids", []))
    except Exception:
        return 0
