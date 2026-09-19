"""Unit tests for the static architecture content loader.

These also act as a content lint: every section in the registry must
ship a well-formed pre-authored file, and every diagram must match the
dialect its `SectionSpec` declares.
"""
from __future__ import annotations

from openexecutive.architecture import prebuilt
from openexecutive.architecture.sections import SECTIONS

_REQUIRED_KEYS = {"section_id", "title", "markdown", "mermaid", "generated_at"}


def test_every_section_has_prebuilt_content() -> None:
    for spec in SECTIONS:
        data = prebuilt.get_prebuilt(spec.id)
        assert data is not None, f"missing prebuilt content for {spec.id}"
        assert set(data) >= _REQUIRED_KEYS, f"bad keys for {spec.id}"
        assert data["section_id"] == spec.id
        assert data["markdown"].strip(), f"empty markdown for {spec.id}"


def test_list_prebuilt_covers_registry_exactly() -> None:
    listed = set(prebuilt.list_prebuilt())
    registry = {s.id for s in SECTIONS}
    assert listed == registry


def test_markdown_has_no_top_level_heading() -> None:
    # The UI renders the section title; the body must not repeat it.
    for spec in SECTIONS:
        data = prebuilt.get_prebuilt(spec.id)
        assert data is not None
        assert not data["markdown"].lstrip().startswith("#"), spec.id


def test_mermaid_matches_declared_dialect() -> None:
    for spec in SECTIONS:
        data = prebuilt.get_prebuilt(spec.id)
        assert data is not None
        mermaid = data["mermaid"]
        if not spec.wants_mermaid:
            assert mermaid is None, f"{spec.id} should have no diagram"
            continue
        assert mermaid, f"{spec.id} wants a diagram but has none"
        head = mermaid.lstrip().splitlines()[0]
        if spec.diagram_kind == "sequence":
            assert head.startswith("sequenceDiagram"), f"{spec.id}: {head!r}"
        else:
            assert head.startswith(("flowchart", "graph")), f"{spec.id}: {head!r}"


def test_get_prebuilt_unknown_returns_none() -> None:
    assert prebuilt.get_prebuilt("does-not-exist") is None


def test_get_prebuilt_rejects_path_traversal() -> None:
    assert prebuilt.get_prebuilt("../cache") is None
    assert prebuilt.get_prebuilt("..") is None
    assert prebuilt.get_prebuilt("a/b") is None
