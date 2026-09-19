"""Importing Agent Skills-format packs (ai-marketing-skills) as builtin skills."""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.knowledge import agent_skills
from openexecutive.knowledge.agent_skills import (
    LICENSE_FILENAME,
    convert_skill,
    default_marketing_pack,
    import_pack,
)
from openexecutive.knowledge.skills import SkillParseError, parse_skill_file, parse_skill_text
from openexecutive.knowledge.skills_index import BUILTIN_SKILLS_PATH

_LICENSE = "MIT License\n\nCopyright (c) 2026 Example Ltd\n\nPermission is hereby granted…\n"


def _skill_md(
    name: str = "keyword-research",
    description: str = (
        "Use this skill to expand seed topics and score priorities. "
        "Trigger it when building a keyword universe or planning SEO content."
    ),
    compatibility: str = "Requires Keywords Everywhere MCP.",
) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        "license: MIT\n"
        f'compatibility: "{compatibility}"\n'
        "metadata:\n  author: superamped\n"
        "---\n\n"
        f"# {name.replace('-', ' ').title()}\n\n## Usage\n\nDo the thing.\n"
    )


def _pack(root: Path, skills: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    (root / "LICENSE").write_text(_LICENSE, encoding="utf-8")
    for directory, text in skills.items():
        path = root / "skills" / "research" / directory / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    return root


def _convert(skill_md: str) -> str:
    return convert_skill(
        skill_md,
        category="marketing",
        source_path="skills/x/SKILL.md",
        copyright_line="Copyright (c) 2026 Example Ltd",
    )[1]


# ---------------------------------------------------------------------------
# convert_skill
# ---------------------------------------------------------------------------


def test_convert_splits_the_description_into_what_and_when() -> None:
    name, text = convert_skill(
        _skill_md(), category="marketing", source_path="skills/research/keyword-research/SKILL.md"
    )
    skill = parse_skill_text(text, Path(f"{name}.md"), source="builtin")
    assert name == "keyword-research"
    assert skill.frontmatter.description == "Expand seed topics and score priorities."
    assert skill.frontmatter.when_to_use == (
        "When building a keyword universe or planning SEO content."
    )
    assert skill.frontmatter.category == "marketing"


def test_convert_keeps_requirements_under_the_title_and_credits_the_source() -> None:
    body = _convert(_skill_md()).split("---\n", 2)[2]
    assert body.lstrip().startswith(
        "# Keyword Research\n\n> **Requirements:** Requires Keywords Everywhere MCP.\n\n## Usage"
    )
    footer = body.rstrip().splitlines()[-1]
    assert "ai-marketing-skills" in footer
    assert "`skills/x/SKILL.md`" in footer
    assert "Copyright (c) 2026 Example Ltd, MIT License" in footer
    assert LICENSE_FILENAME in footer


@pytest.mark.parametrize(
    ("compatibility", "expected"),
    [
        ("No special requirements.", None),
        (
            "No special requirements. Accepts campaign data as CSV.",
            "> **Requirements:** Accepts campaign data as CSV.",
        ),
    ],
)
def test_convert_drops_the_no_requirements_boilerplate(
    compatibility: str, expected: str | None
) -> None:
    text = _convert(_skill_md(compatibility=compatibility))
    if expected is None:
        assert "Requirements" not in text
    else:
        assert expected in text


@pytest.mark.parametrize(
    "skill_md",
    [
        "# no frontmatter\n",
        _skill_md(description="Writes posts."),  # not "Use this skill to … Trigger it …"
        _skill_md(name="Keyword-Research"),  # would collide by case on Windows/macOS
        _skill_md(name='"keyword-research\\n"'),  # trailing newline in the name
        "---\nname: [keyword-research\n---\n\n# Body\n",  # malformed YAML
        "---\n- keyword-research\n---\n\n# Body\n",  # frontmatter isn't a mapping
    ],
)
def test_convert_rejects_files_outside_the_pack_conventions(skill_md: str) -> None:
    with pytest.raises(SkillParseError):
        _convert(skill_md)


# ---------------------------------------------------------------------------
# import_pack
# ---------------------------------------------------------------------------


def test_import_writes_then_leaves_unchanged_files_alone(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "pack", {"keyword-research": _skill_md()})
    target = tmp_path / "marketing"

    first = import_pack(pack, target)
    second = import_pack(pack, target)

    assert first.written == ["keyword-research"]
    assert second.written == [] and second.unchanged == ["keyword-research"]
    parse_skill_file(target / "keyword-research.md", source="builtin")


def test_import_ships_the_pack_license_next_to_the_skills(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "pack", {"keyword-research": _skill_md()})
    target = tmp_path / "marketing"
    import_pack(pack, target)
    assert (target / LICENSE_FILENAME).read_text(encoding="utf-8") == _LICENSE


def test_import_refuses_a_pack_without_a_license(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "pack", {"keyword-research": _skill_md()})
    (pack / "LICENSE").unlink()
    with pytest.raises(SkillParseError, match="LICENSE"):
        import_pack(pack, tmp_path / "marketing")


def test_import_removes_generated_skills_that_left_the_pack(tmp_path: Path) -> None:
    pack = _pack(
        tmp_path / "pack",
        {"keyword-research": _skill_md(), "old-skill": _skill_md(name="old-skill")},
    )
    target = tmp_path / "marketing"
    import_pack(pack, target)
    hand_written = target / "positioning-statement.md"
    hand_written.write_text("hand-written skill", encoding="utf-8")

    (pack / "skills" / "research" / "old-skill" / "SKILL.md").unlink()
    report = import_pack(pack, target)

    assert report.removed == ["old-skill"]
    assert not (target / "old-skill.md").exists()
    assert hand_written.read_text(encoding="utf-8") == "hand-written skill"


@pytest.mark.parametrize(
    ("existing_name", "existing_text"),
    [
        ("keyword-research.md", "mine"),
        # A different case is the same file on Windows and macOS.
        ("Keyword-Research.md", "mine"),
        # Quoting the generator's marker mid-file doesn't make a skill generated.
        ("keyword-research.md", "*Imported from [ai-marketing-skills] …\n\nmine"),
    ],
)
def test_import_never_overwrites_a_hand_written_skill(
    tmp_path: Path, existing_name: str, existing_text: str
) -> None:
    pack = _pack(tmp_path / "pack", {"keyword-research": _skill_md()})
    target = tmp_path / "marketing"
    target.mkdir()
    (target / existing_name).write_text(existing_text, encoding="utf-8")

    with pytest.raises(SkillParseError, match="collide"):
        import_pack(pack, target)
    assert (target / existing_name).read_text(encoding="utf-8") == existing_text


def test_default_pack_path_survives_a_flattened_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Docker image copies packages/core to /app: too shallow for the monorepo root.
    monkeypatch.setattr(agent_skills, "__file__", "/app/openexecutive/knowledge/agent_skills.py")
    assert not (default_marketing_pack() / "skills").is_dir()


# ---------------------------------------------------------------------------
# The committed skills
# ---------------------------------------------------------------------------


def test_every_builtin_skill_parses() -> None:
    paths = sorted(BUILTIN_SKILLS_PATH.rglob("*.md"))
    assert paths
    for path in paths:
        parse_skill_file(path, source="builtin")


@pytest.mark.skipif(
    not (default_marketing_pack() / "skills").is_dir(),
    reason="ai-marketing-skills is not checked out next to OpenExecutive",
)
def test_committed_marketing_skills_match_the_pack(tmp_path: Path) -> None:
    """Catches hand edits to generated files, a pack update that wasn't
    re-imported, and generated files left behind by a removed pack skill."""
    regenerated = tmp_path / "marketing"
    import_pack(default_marketing_pack(), regenerated)
    committed = BUILTIN_SKILLS_PATH / "marketing"

    def generated_files(directory: Path) -> dict[str, str]:
        texts = {path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()}
        return {
            name: text
            for name, text in texts.items()
            if name == LICENSE_FILENAME or "*Imported from [ai-marketing-skills]" in text
        }

    assert generated_files(committed) == generated_files(regenerated), (
        "re-run scripts/import_marketing_skills.py"
    )
