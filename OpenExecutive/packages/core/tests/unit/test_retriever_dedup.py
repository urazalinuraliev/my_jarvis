"""Unit tests for retriever text-based deduplication of multi-domain hits."""
from __future__ import annotations

from openexecutive.knowledge.retriever import _dedupe_by_text


def test_dedupe_drops_repeated_text_preserving_order() -> None:
    rows = [
        {"text": "alpha", "metadata": {"domain": "finance"}, "distance": 0.1},
        {"text": "alpha", "metadata": {"domain": "strategy"}, "distance": 0.2},
        {"text": "beta", "metadata": {"domain": "hr"}, "distance": 0.3},
        {"text": "alpha", "metadata": {"domain": "marketing"}, "distance": 0.4},
    ]
    out = _dedupe_by_text(rows)
    assert [r["text"] for r in out] == ["alpha", "beta"]
    # First occurrence wins (highest-relevance copy)
    assert out[0]["metadata"]["domain"] == "finance"


def test_dedupe_is_a_noop_when_all_unique() -> None:
    rows = [
        {"text": "a", "metadata": {}, "distance": 0.0},
        {"text": "b", "metadata": {}, "distance": 0.0},
        {"text": "c", "metadata": {}, "distance": 0.0},
    ]
    assert _dedupe_by_text(rows) == rows


def test_dedupe_handles_empty() -> None:
    assert _dedupe_by_text([]) == []
