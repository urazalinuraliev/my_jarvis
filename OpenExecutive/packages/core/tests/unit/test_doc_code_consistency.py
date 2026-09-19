"""Doc/code consistency guards.

These tests fail when the curated architecture facts drift from what the code
actually does — the failure mode the ``/architecture`` page is most prone to
(see ``CLAUDE.md`` -> "Architecture Docs"). They are deliberately coupled to
BOTH the YAML and the code, so changing one without the other breaks CI.

Current coverage: the ``wait_for_human`` resume invariant (the canonical drift
example — docs once claimed paused workflows auto-continue while the code
defers full generator resume to "Phase 7"). Add further invariants here as
they are identified.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from openexecutive.architecture import facts as facts_mod
from openexecutive.workflows import resumer


def _load_facts() -> dict[str, Any]:
    path = Path(facts_mod.__file__).parent / "architecture-facts.yaml"
    return yaml.safe_load(path.read_text())


def _resumer_source() -> str:
    return Path(resumer.__file__).read_text()


def test_resumer_still_defers_full_generator_resume() -> None:
    """Pins the code reality the docs describe: full generator resume is NOT
    implemented (deferred to "Phase 7"). If someone implements it and removes
    the marker, this fails — prompting them to update both the code note and
    the architecture facts (see the doc test below)."""
    src = _resumer_source()
    assert "Phase 7" in src, (
        "resumer.py no longer marks full generator resume as deferred. If "
        "resume was implemented, update architecture-facts.yaml "
        "(workflows.human_in_the_loop) and this test together."
    )
    # The capture path that IS shipped must still exist...
    assert hasattr(resumer, "apply_resolution")
    # ...and no public auto-continue entry point should exist yet.
    assert not hasattr(resumer, "resume_run")
    assert not hasattr(resumer, "continue_run")


def test_hitl_doc_does_not_overclaim_resume() -> None:
    """The facts must not claim paused workflows auto-continue while the code
    defers that — the exact drift this guard exists to catch."""
    hitl = _load_facts()["workflows"]["human_in_the_loop"]

    # The retired overclaim: resumer "continues the next step".
    assert "continues the next step" not in hitl, (
        "architecture-facts.yaml claims wait_for_human continues the next "
        "step, but resumer.py defers full generator resume to Phase 7."
    )
    # And it must positively signal the deferral so the doc stays honest.
    assert ("Phase 7" in hitl) or ("NOT YET SHIPPED" in hitl)


def test_hitl_doc_and_code_agree_on_resume() -> None:
    """Couple the two directly: if the code defers resume, the doc must say so
    (and vice versa). The one assertion that ties code reality to the page."""
    code_defers = "Phase 7" in _resumer_source()
    hitl = _load_facts()["workflows"]["human_in_the_loop"]
    doc_admits_gap = ("Phase 7" in hitl) or ("NOT YET SHIPPED" in hitl)
    assert code_defers == doc_admits_gap, (
        "Resume status disagrees between resumer.py and architecture-facts.yaml "
        "(workflows.human_in_the_loop). Update both."
    )
