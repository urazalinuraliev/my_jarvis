from __future__ import annotations

from pathlib import Path

from openexecutive.architecture import cache as cache_mod
from openexecutive.architecture.cache import SectionContent


def _make(section_id: str, facts_hash: str = "h-1", mermaid: str | None = None) -> SectionContent:
    return SectionContent(
        section_id=section_id,
        markdown="# body",
        mermaid=mermaid,
        facts_hash=facts_hash,
        generated_at="2026-05-19T00:00:00+00:00",
    )


def test_get_returns_none_when_missing(tmp_path: Path) -> None:
    db = tmp_path / "arch.db"
    assert cache_mod.get("overview", db_path=db) is None


def test_put_and_get_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "arch.db"
    cache_mod.put(_make("overview", facts_hash="h-1", mermaid="flowchart TD\nA-->B"), db_path=db)
    cached = cache_mod.get("overview", db_path=db)
    assert cached is not None
    assert cached.section_id == "overview"
    assert cached.facts_hash == "h-1"
    assert cached.mermaid is not None and cached.mermaid.startswith("flowchart")


def test_put_upserts_on_conflict(tmp_path: Path) -> None:
    db = tmp_path / "arch.db"
    cache_mod.put(_make("overview", facts_hash="h-1"), db_path=db)
    cache_mod.put(
        SectionContent(
            section_id="overview",
            markdown="# new",
            mermaid=None,
            facts_hash="h-2",
            generated_at="2026-05-20T00:00:00+00:00",
        ),
        db_path=db,
    )
    cached = cache_mod.get("overview", db_path=db)
    assert cached is not None
    assert cached.facts_hash == "h-2"
    assert cached.markdown == "# new"


def test_is_fresh(tmp_path: Path) -> None:
    db = tmp_path / "arch.db"
    cache_mod.put(_make("overview", facts_hash="h-1"), db_path=db)
    assert cache_mod.is_fresh("overview", "h-1", db_path=db) is True
    assert cache_mod.is_fresh("overview", "h-2", db_path=db) is False
    assert cache_mod.is_fresh("absent", "h-1", db_path=db) is False
