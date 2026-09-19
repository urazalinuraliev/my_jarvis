"""Cache-safety guards for the Committee path.

If the committee path mutates the cached system blocks, every request will
miss the Anthropic prompt cache and costs jump ~10x. These tests freeze
the expected invariants so a future refactor that breaks them fails loudly.
"""
from __future__ import annotations

from openexecutive.prompts.cache_manager import build_system_blocks


def test_build_system_blocks_is_byte_identical_across_calls() -> None:
    """Two back-to-back calls with identical inputs must produce byte-equal
    block text. Cache keys hash the text — any divergence (timestamps,
    object ids leaking in, etc.) would silently destroy cache hits."""
    a = build_system_blocks(company_profile=None, mcp_enabled=False)
    b = build_system_blocks(company_profile=None, mcp_enabled=False)
    assert a == b
    assert [blk["text"] for blk in a] == [blk["text"] for blk in b]


def test_committee_path_does_not_mutate_system_blocks() -> None:
    """Sanity: ensure the committee module never imports/calls something
    that mutates the persona / knowledge index blocks. We check by hashing
    the block list before importing the committee modules and again after."""
    import hashlib

    def _digest() -> str:
        blocks = build_system_blocks(company_profile=None, mcp_enabled=False)
        joined = "\n".join(b["text"] for b in blocks)
        return hashlib.sha256(joined.encode()).hexdigest()

    before = _digest()

    import openexecutive.orchestrator.committee  # noqa: F401
    import openexecutive.orchestrator.committee_reviewers  # noqa: F401
    import openexecutive.prompts.committee_prompts  # noqa: F401

    after = _digest()
    assert before == after
