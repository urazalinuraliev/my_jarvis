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
    SkillParseError,
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


def _iter_skill_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.md"))


async def seed_builtin_skills(store: ChromaDBStore | None = None, force: bool = False) -> int:
    """Index every built-in skill on disk. Idempotent: skipped if collection non-empty."""
    if store is None:
        from openexecutive.config import get_settings

        store = ChromaDBStore(persist_directory=get_settings().vector_store_path)

    if not force and store.get_collection_count(SKILLS_COLLECTION) > 0:
        return 0

    count = 0
    for path in _iter_skill_files(BUILTIN_SKILLS_PATH):
        try:
            skill = parse_skill_file(path, source="builtin")
        except SkillParseError as e:
            logger.warning("Skipping malformed skill %s: %s", path, e)
            continue
        index_skill(skill, store)
        count += 1
    return count


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
