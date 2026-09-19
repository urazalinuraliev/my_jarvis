"""``list_fixtures`` exposes a compact department + people summary per fixture so
the Company Simulator (/demo) cards can show the org shape without a second
round-trip. The parsing helpers must be defensive: a missing or malformed
``departments.yaml`` / ``people.yaml`` yields ``[]`` rather than throwing or
dropping the fixture.
"""
from __future__ import annotations

from pathlib import Path

from openexecutive.cli.fixture_loader import (
    _summarize_departments,
    _summarize_people,
    list_fixtures,
)

# --------------------------------------------------------------------------- #
# _summarize_departments                                                       #
# --------------------------------------------------------------------------- #


def test_summarize_departments_parses_title_and_head(tmp_path: Path) -> None:
    p = tmp_path / "departments.yaml"
    p.write_text(
        "departments:\n"
        "  - slug: strategy\n"
        "    title: Strategy & Risk\n"
        "    head_person_name: Taylor Brooks\n"
        "  - slug: finance\n"
        "    title: Finance\n"
    )
    assert _summarize_departments(p) == [
        {"title": "Strategy & Risk", "head": "Taylor Brooks"},
        {"title": "Finance", "head": None},
    ]


def test_summarize_departments_falls_back_to_slug(tmp_path: Path) -> None:
    p = tmp_path / "departments.yaml"
    p.write_text("departments:\n  - slug: ops\n")
    assert _summarize_departments(p) == [{"title": "ops", "head": None}]


def test_summarize_departments_missing_or_malformed(tmp_path: Path) -> None:
    assert _summarize_departments(tmp_path / "absent.yaml") == []

    bad = tmp_path / "bad.yaml"
    bad.write_text("departments: [unbalanced\n")  # invalid YAML
    assert _summarize_departments(bad) == []

    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert _summarize_departments(empty) == []


# --------------------------------------------------------------------------- #
# _summarize_people                                                            #
# --------------------------------------------------------------------------- #


def test_summarize_people_parses_name_role_principal(tmp_path: Path) -> None:
    p = tmp_path / "people.yaml"
    p.write_text(
        "people:\n"
        "  - full_name: Jordan Avery\n"
        "    role: CEO\n"
        "    is_principal: true\n"
        "  - full_name: Sam Rivera\n"
        "    role: Head of Finance\n"
    )
    assert _summarize_people(p) == [
        {"name": "Jordan Avery", "role": "CEO", "is_principal": True},
        {"name": "Sam Rivera", "role": "Head of Finance", "is_principal": False},
    ]


def test_summarize_people_skips_nameless_and_defaults_role(tmp_path: Path) -> None:
    p = tmp_path / "people.yaml"
    p.write_text(
        "people:\n"
        "  - role: ghost with no name\n"  # dropped — no full_name
        "  - full_name: Real Person\n"
    )
    assert _summarize_people(p) == [
        {"name": "Real Person", "role": "", "is_principal": False}
    ]


def test_summarize_people_missing_or_malformed(tmp_path: Path) -> None:
    assert _summarize_people(tmp_path / "absent.yaml") == []

    bad = tmp_path / "bad.yaml"
    bad.write_text("people: {oops\n")  # invalid YAML
    assert _summarize_people(bad) == []


# --------------------------------------------------------------------------- #
# list_fixtures wiring                                                          #
# --------------------------------------------------------------------------- #


def test_list_fixtures_includes_org_summaries() -> None:
    """Every fixture in the repo carries the new keys with list values, and a
    known fixture resolves its full department + leadership shape.
    """
    fixtures = {f["name"]: f for f in list_fixtures()}
    assert fixtures, "expected at least one fixture on disk"

    for fx in fixtures.values():
        assert isinstance(fx["departments"], list)
        assert isinstance(fx["people"], list)

    meridian = fixtures.get("meridian_petroleum")
    if meridian is not None:  # guard so the test survives a future fixture prune
        assert len(meridian["departments"]) == 7
        assert all(d["title"] for d in meridian["departments"])
        assert len(meridian["people"]) == 5
        assert sum(1 for p in meridian["people"] if p["is_principal"]) == 1
