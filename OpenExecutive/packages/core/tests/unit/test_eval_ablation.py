"""Smoke tests for the RAG ablation harness (no API calls).

Exercises the pure aggregation/reporting logic. The live ``run_ablation()``
path makes paid LLM calls and is intentionally not executed here — only its
shape (async, driven by the standard harness) is asserted.
"""
from __future__ import annotations

import inspect

from openexecutive.evals.ablation import build_report, format_report, run_ablation


def test_build_report_computes_per_domain_delta() -> None:
    id_to_domain = {
        "finance_001": "finance",
        "finance_002": "finance",
        "hr_001": "hr",
    }
    on = {"finance_001": 4.0, "finance_002": 5.0, "hr_001": 3.0}
    off = {"finance_001": 3.0, "finance_002": 4.0, "hr_001": 3.0}

    report = build_report(id_to_domain, on, off)

    assert report["n_compared"] == 3
    assert report["n_skipped"] == 0
    # finance deltas +1, +1 -> avg +1.0 ; hr delta 0 -> avg 0.0
    assert report["per_domain"]["finance"]["n"] == 2
    assert report["per_domain"]["finance"]["avg_on_minus_off"] == 1.0
    assert report["per_domain"]["hr"]["avg_on_minus_off"] == 0.0
    # overall avg of (+1, +1, 0)
    assert abs(report["overall_avg_on_minus_off"] - (2.0 / 3.0)) < 1e-9


def test_build_report_skips_scenarios_that_errored_in_one_arm() -> None:
    id_to_domain = {"a": "finance", "b": "finance"}
    on = {"a": 4.0, "b": None}  # b errored in the on arm
    off = {"a": 3.0, "b": 2.0}

    report = build_report(id_to_domain, on, off)

    assert report["n_compared"] == 1
    assert report["n_skipped"] == 1
    assert report["skipped_ids"] == ["b"]
    assert report["per_domain"]["finance"]["n"] == 1


def test_build_report_handles_empty_input() -> None:
    report = build_report({}, {}, {})
    assert report["n_compared"] == 0
    assert report["overall_avg_on_minus_off"] == 0.0
    assert report["per_domain"] == {}


def test_format_report_returns_readable_string() -> None:
    report = build_report(
        {"finance_001": "finance"}, {"finance_001": 4.0}, {"finance_001": 3.0}
    )
    out = format_report(report)
    assert isinstance(out, str)
    assert "finance" in out
    assert "ON vs OFF" in out


def test_run_ablation_is_a_coroutine() -> None:
    # Structural guard: the live entry point stays async (driven by the async
    # run_scenarios harness). Not executed here — it makes paid LLM calls.
    assert inspect.iscoroutinefunction(run_ablation)
