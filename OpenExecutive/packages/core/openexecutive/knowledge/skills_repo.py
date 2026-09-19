"""Filesystem CRUD for skills, shared by API routes and Executive tool handlers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openexecutive.knowledge.skills import (
    SKILL_CATEGORIES,
    Skill,
    SkillFrontmatter,
    SkillParseError,
    SkillSource,
    parse_skill_file,
    serialize_skill,
    validate_skill_name,
)
from openexecutive.knowledge.skills_index import (
    BUILTIN_SKILLS_PATH,
    _company_skills_path,
    delete_skill_index,
    index_skill,
)
from openexecutive.knowledge.store import ChromaDBStore

logger = logging.getLogger(__name__)


class SkillNotFoundError(LookupError):
    pass


class SkillConflictError(ValueError):
    pass


class SkillReadOnlyError(PermissionError):
    """Raised when a mutating operation targets a built-in skill."""


def _skill_path(source: SkillSource, category: str, name: str) -> Path:
    base = BUILTIN_SKILLS_PATH if source == "builtin" else _company_skills_path()
    return base / category / f"{name}.md"


def _find_skill_on_disk(name: str) -> tuple[Path, SkillSource] | None:
    """Return the (path, source) of a skill by name, searching both trees.

    Built-in wins on collision (though uniqueness is enforced at create time).
    """
    for source, root in (("builtin", BUILTIN_SKILLS_PATH), ("company", _company_skills_path())):
        if not root.exists():
            continue
        for path in root.rglob(f"{name}.md"):
            return path, source  # type: ignore[return-value]
    return None


def list_skills() -> list[Skill]:
    """Walk both trees, parse all skills, return them sorted by name. Malformed skills are skipped."""
    out: list[Skill] = []
    for source, root in (("builtin", BUILTIN_SKILLS_PATH), ("company", _company_skills_path())):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                out.append(parse_skill_file(path, source=source))  # type: ignore[arg-type]
            except SkillParseError as e:
                logger.warning("Skipping malformed skill %s: %s", path, e)
    out.sort(key=lambda s: (s.frontmatter.category, s.frontmatter.name))
    return out


def get_skill(name: str) -> Skill:
    validate_skill_name(name)
    found = _find_skill_on_disk(name)
    if found is None:
        raise SkillNotFoundError(f"Skill '{name}' not found")
    path, source = found
    return parse_skill_file(path, source=source)


def create_skill(
    name: str,
    description: str,
    when_to_use: str,
    category: str,
    body: str,
    store: ChromaDBStore,
) -> Skill:
    """Create a new company skill. 409 if name already exists in either tree."""
    validate_skill_name(name)
    if category not in SKILL_CATEGORIES:
        raise SkillParseError(
            f"Unknown category '{category}'. Valid: {', '.join(SKILL_CATEGORIES)}"
        )
    if _find_skill_on_disk(name) is not None:
        raise SkillConflictError(f"Skill '{name}' already exists")

    frontmatter = SkillFrontmatter(
        name=name,
        description=description,
        when_to_use=when_to_use,
        category=category,
    )
    path = _skill_path("company", category, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_skill(frontmatter, body), encoding="utf-8")

    skill = Skill(frontmatter=frontmatter, body=body, source="company", path=str(path))
    index_skill(skill, store)
    return skill


def update_skill(
    name: str,
    description: str,
    when_to_use: str,
    category: str,
    body: str,
    store: ChromaDBStore,
) -> Skill:
    """Update an existing company skill. Built-in skills are read-only."""
    validate_skill_name(name)
    found = _find_skill_on_disk(name)
    if found is None:
        raise SkillNotFoundError(f"Skill '{name}' not found")
    _, source = found
    if source == "builtin":
        raise SkillReadOnlyError(f"Skill '{name}' is built-in and cannot be modified")
    if category not in SKILL_CATEGORIES:
        raise SkillParseError(
            f"Unknown category '{category}'. Valid: {', '.join(SKILL_CATEGORIES)}"
        )

    old_path, _ = found
    new_path = _skill_path("company", category, name)

    frontmatter = SkillFrontmatter(
        name=name,
        description=description,
        when_to_use=when_to_use,
        category=category,
    )
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(serialize_skill(frontmatter, body), encoding="utf-8")
    if new_path != old_path and old_path.exists():
        old_path.unlink()

    skill = Skill(frontmatter=frontmatter, body=body, source="company", path=str(new_path))
    index_skill(skill, store)
    return skill


def delete_skill(name: str, store: ChromaDBStore) -> None:
    """Delete a company skill. Built-in skills are read-only."""
    validate_skill_name(name)
    found = _find_skill_on_disk(name)
    if found is None:
        raise SkillNotFoundError(f"Skill '{name}' not found")
    path, source = found
    if source == "builtin":
        raise SkillReadOnlyError(f"Skill '{name}' is built-in and cannot be deleted")

    path.unlink()
    delete_skill_index(name, source, store)


def skill_to_dict(skill: Skill, include_body: bool = True) -> dict[str, Any]:
    fm = skill.frontmatter
    out: dict[str, Any] = {
        "name": fm.name,
        "category": fm.category,
        "description": fm.description,
        "when_to_use": fm.when_to_use,
        "source": skill.source,
        "filename": Path(skill.path).name,
    }
    if include_body:
        out["body"] = skill.body
    return out
