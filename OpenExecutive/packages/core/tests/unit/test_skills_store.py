"""End-to-end tests for the skill repo + ChromaDB index using a tmp_path store."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from openexecutive.knowledge import skills_index, skills_repo
from openexecutive.knowledge.skills_index import (
    count_skills,
    search_skills,
    seed_builtin_skills,
)
from openexecutive.knowledge.skills_repo import (
    SkillConflictError,
    SkillNotFoundError,
    SkillReadOnlyError,
    create_skill,
    delete_skill,
    get_skill,
    list_skills,
    update_skill,
)
from openexecutive.knowledge.store import ChromaDBStore


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ChromaDBStore]:
    """Point both skill trees at temp dirs and give us a fresh ChromaDB."""
    builtin_root = tmp_path / "builtin_skills"
    company_root = tmp_path / "company_skills"
    builtin_root.mkdir()
    company_root.mkdir()

    monkeypatch.setattr(skills_index, "BUILTIN_SKILLS_PATH", builtin_root)
    monkeypatch.setattr(skills_repo, "BUILTIN_SKILLS_PATH", builtin_root)
    monkeypatch.setattr(skills_index, "_company_skills_path", lambda: company_root)
    monkeypatch.setattr(skills_repo, "_company_skills_path", lambda: company_root)

    store = ChromaDBStore(persist_directory=str(tmp_path / "chroma"))
    yield store


def _write_builtin(root: Path, category: str, name: str) -> Path:
    target = root / category / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\nname: {name}\ndescription: built-in {name}\n"
        f"when_to_use: tests\ncategory: {category}\n---\n\n# body of {name}\n",
        encoding="utf-8",
    )
    return target


def test_create_search_get_delete_roundtrip(isolated: ChromaDBStore) -> None:
    skill = create_skill(
        name="monthly-revenue-review",
        description="A monthly revenue review template",
        when_to_use="Each month-end close",
        category="finance",
        body="# Revenue review\n\nSteps...",
        store=isolated,
    )
    assert skill.source == "company"
    assert skill.frontmatter.name == "monthly-revenue-review"

    fetched = get_skill("monthly-revenue-review")
    assert fetched.frontmatter.description == "A monthly revenue review template"
    assert "Revenue review" in fetched.body

    hits = search_skills("monthly revenue close", isolated, n_results=3)
    assert any(h["name"] == "monthly-revenue-review" for h in hits)
    assert all("body" not in h for h in hits), "search_skills must not include body"

    delete_skill("monthly-revenue-review", store=isolated)
    with pytest.raises(SkillNotFoundError):
        get_skill("monthly-revenue-review")
    hits_after = search_skills("monthly revenue close", isolated, n_results=3)
    assert not any(h["name"] == "monthly-revenue-review" for h in hits_after)


def test_duplicate_create_raises_conflict(isolated: ChromaDBStore) -> None:
    create_skill(
        name="x",
        description="d",
        when_to_use="w",
        category="general",
        body="b",
        store=isolated,
    )
    with pytest.raises(SkillConflictError):
        create_skill(
            name="x",
            description="d2",
            when_to_use="w2",
            category="general",
            body="b2",
            store=isolated,
        )


def test_builtin_skills_are_readonly(
    isolated: ChromaDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_builtin(skills_index.BUILTIN_SKILLS_PATH, "finance", "builtin-thing")
    # Index it via the same path the lifespan would use.
    import asyncio

    asyncio.run(seed_builtin_skills(store=isolated, force=True))

    fetched = get_skill("builtin-thing")
    assert fetched.source == "builtin"

    with pytest.raises(SkillReadOnlyError):
        update_skill(
            name="builtin-thing",
            description="x",
            when_to_use="y",
            category="finance",
            body="z",
            store=isolated,
        )
    with pytest.raises(SkillReadOnlyError):
        delete_skill("builtin-thing", store=isolated)

    # Duplicate name across builtin tree also blocks company create.
    with pytest.raises(SkillConflictError):
        create_skill(
            name="builtin-thing",
            description="d",
            when_to_use="w",
            category="general",
            body="b",
            store=isolated,
        )


def test_update_changes_category_moves_file(isolated: ChromaDBStore) -> None:
    create_skill(
        name="mover",
        description="d",
        when_to_use="w",
        category="finance",
        body="b",
        store=isolated,
    )
    original = skills_repo._company_skills_path() / "finance" / "mover.md"
    assert original.exists()

    update_skill(
        name="mover",
        description="d2",
        when_to_use="w2",
        category="strategy",
        body="b2",
        store=isolated,
    )
    moved = skills_repo._company_skills_path() / "strategy" / "mover.md"
    assert moved.exists()
    assert not original.exists()


def test_seed_is_idempotent(isolated: ChromaDBStore) -> None:
    import asyncio

    _write_builtin(skills_index.BUILTIN_SKILLS_PATH, "strategy", "alpha")
    _write_builtin(skills_index.BUILTIN_SKILLS_PATH, "finance", "beta")
    first = asyncio.run(seed_builtin_skills(store=isolated, force=True))
    second = asyncio.run(seed_builtin_skills(store=isolated))
    assert first == 2
    assert second == 0
    assert count_skills(isolated, source="builtin") == 2


def test_list_includes_both_sources(isolated: ChromaDBStore) -> None:
    import asyncio

    _write_builtin(skills_index.BUILTIN_SKILLS_PATH, "strategy", "alpha")
    asyncio.run(seed_builtin_skills(store=isolated, force=True))
    create_skill(
        name="user-skill",
        description="d",
        when_to_use="w",
        category="general",
        body="b",
        store=isolated,
    )

    all_skills = list_skills()
    sources = {s.source for s in all_skills}
    assert sources == {"builtin", "company"}
    names = {s.frontmatter.name for s in all_skills}
    assert names == {"alpha", "user-skill"}
