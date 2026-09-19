"""User-guide documentation surface.

The /guide page in the UI is a plain-language overview of every
user-facing feature — kept separate from the technical /architecture
reference. It is rendered from static, hand-authored content under
``prebuilt/<section_id>.json`` — one file per entry in
``sections.GUIDE_SECTIONS``. The API (`api/routes/guide.py`) only reads
those files; nothing on the serving path calls an LLM.
"""
from openexecutive.guide.prebuilt import get_prebuilt, list_prebuilt
from openexecutive.guide.sections import GUIDE_SECTIONS, GuideSection, get_section

__all__ = [
    "GUIDE_SECTIONS",
    "GuideSection",
    "get_prebuilt",
    "get_section",
    "list_prebuilt",
]
