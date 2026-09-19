"""Unit tests for the YAML frontmatter parser used by the skills feature."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.knowledge.skills import (
    SkillFrontmatter,
    SkillParseError,
    parse_skill_text,
    serialize_skill,
    validate_skill_name,
)


def _good_text(name: str = "test-skill", category: str = "finance") -> str:
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: A test skill\n"
        f"when_to_use: User asks for a test\n"
        f"category: {category}\n"
        f"---\n\n"
        f"# Body\n\nSome content here.\n"
    )


def test_parse_valid_skill(tmp_path: Path) -> None:
    path = tmp_path / "test-skill.md"
    skill = parse_skill_text(_good_text(), path, source="company")
    assert skill.frontmatter.name == "test-skill"
    assert skill.frontmatter.category == "finance"
    assert skill.frontmatter.description == "A test skill"
    assert skill.frontmatter.when_to_use == "User asks for a test"
    assert skill.source == "company"
    assert "# Body" in skill.body
    assert "Some content here." in skill.body


def test_serialize_roundtrip(tmp_path: Path) -> None:
    fm = SkillFrontmatter(
        name="round-trip",
        description="desc",
        when_to_use="when",
        category="general",
    )
    body = "# Hello\n\nWorld.\n"
    serialized = serialize_skill(fm, body)
    path = tmp_path / "round-trip.md"
    parsed = parse_skill_text(serialized, path, source="company")
    assert parsed.frontmatter == fm
    assert "# Hello" in parsed.body
    assert "World." in parsed.body


def test_missing_frontmatter_raises(tmp_path: Path) -> None:
    path = tmp_path / "no-fm.md"
    with pytest.raises(SkillParseError, match="missing YAML frontmatter"):
        parse_skill_text("# No frontmatter\n\nJust a body.", path, source="builtin")


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad-yaml.md"
    text = "---\nname: bad-yaml\ndescription: [unclosed\n---\n\nbody\n"
    with pytest.raises(SkillParseError, match="malformed YAML"):
        parse_skill_text(text, path, source="builtin")


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "missing-field.md"
    text = (
        "---\n"
        "name: missing-field\n"
        "description: only a description\n"
        "---\n\nbody\n"
    )
    with pytest.raises(SkillParseError, match="missing required frontmatter field"):
        parse_skill_text(text, path, source="builtin")


def test_filename_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "wrong-name.md"
    with pytest.raises(SkillParseError, match="does not match filename"):
        parse_skill_text(_good_text(name="different-name"), path, source="builtin")


def test_invalid_category_raises(tmp_path: Path) -> None:
    path = tmp_path / "test-skill.md"
    with pytest.raises(SkillParseError, match="unknown category"):
        parse_skill_text(_good_text(category="nonsense"), path, source="builtin")


def test_invalid_skill_name_raises() -> None:
    with pytest.raises(SkillParseError, match="Invalid skill name"):
        validate_skill_name("has spaces")
    with pytest.raises(SkillParseError, match="Invalid skill name"):
        validate_skill_name("has/slash")
    # Underscores and hyphens are fine.
    validate_skill_name("ok_name-1")
