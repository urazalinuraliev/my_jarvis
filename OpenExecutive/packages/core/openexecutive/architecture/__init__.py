"""Architecture documentation surface.

The /architecture page in the UI is rendered from static, hand-authored
content under ``prebuilt/<section_id>.json`` — one file per entry in
``sections.SECTIONS``. The API (`api/routes/architecture.py`) only reads
those files via ``prebuilt.get_prebuilt`` / ``prebuilt.list_prebuilt``;
nothing on the serving path calls an LLM.

The ``facts`` and ``generator`` modules remain as authoring aids (with
``architecture-facts.yaml`` as the curated source-of-truth reference)
for re-authoring a section's content; they are not used at request time.
"""
from openexecutive.architecture.facts import FactsBundle, gather_facts
from openexecutive.architecture.generator import SectionContent, generate_section
from openexecutive.architecture.prebuilt import get_prebuilt, list_prebuilt
from openexecutive.architecture.sections import SECTIONS, SectionSpec, get_section

__all__ = [
    "FactsBundle",
    "SectionContent",
    "SectionSpec",
    "SECTIONS",
    "gather_facts",
    "generate_section",
    "get_prebuilt",
    "list_prebuilt",
    "get_section",
]
