"""RAG ablation harness — quantify how much builtin-knowledge retrieval helps.

Runs the existing eval suite twice — once normally (builtin RAG on) and once
with builtin retrieval disabled (``KNOWLEDGE_BUILTIN_N_RESULTS=0``) — and
reports the per-domain change in the judge's ``overall`` score. A positive
delta means builtin RAG raised the score (it helped); a delta near zero (or
negative) means the builtin knowledge base did not earn its token/latency cost
on that domain.

This answers a question the suite otherwise cannot: *is the builtin knowledge
base actually improving answers, or just adding tokens and latency?*

It reuses the standard harness (``openexecutive.evals.runner.run_scenarios``)
and the configurable retrieval knob in ``knowledge/retriever.py`` — disabling
builtin RAG is simply ``n_builtin = 0`` driven from settings, so no eval-only
code path diverges from production retrieval.

⚠️  Running it makes real, paid LLM calls — about TWICE the normal suite (each
scenario is answered and judged once per arm). It defaults to the ``chat``
suite, the only kind whose retrieval depth follows the configurable default
(the report workflows pass explicit per-call counts and are intentionally out
of scope).

Usage::

    python -m openexecutive.evals.ablation                 # all chat scenarios
    python -m openexecutive.evals.ablation --scenario finance_001
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

# Env var (alias of Settings.knowledge_builtin_n_results) the "off" arm sets to
# disable builtin retrieval. get_settings() is uncached, so flipping it takes
# effect on the next retrieve() call without a process restart.
_BUILTIN_N_ENV = "KNOWLEDGE_BUILTIN_N_RESULTS"


def build_report(
    id_to_domain: dict[str, str],
    on_scores: dict[str, float | None],
    off_scores: dict[str, float | None],
) -> dict[str, Any]:
    """Aggregate two score maps into per-scenario and per-domain deltas.

    ``delta = on - off`` (positive ⇒ builtin RAG helped). Scenarios that
    errored in either arm (score ``None``) are skipped and counted separately.

    Pure function — runs no evals — so it is unit-testable without API calls.
    """
    per_scenario: list[dict[str, Any]] = []
    skipped: list[str] = []
    domain_deltas: dict[str, list[float]] = defaultdict(list)

    for sid, domain in id_to_domain.items():
        on = on_scores.get(sid)
        off = off_scores.get(sid)
        if on is None or off is None:
            skipped.append(sid)
            continue
        delta = on - off
        label = domain or "(none)"
        per_scenario.append(
            {"id": sid, "domain": label, "on": on, "off": off, "delta": delta}
        )
        domain_deltas[label].append(delta)

    per_domain = {
        domain: {"n": len(deltas), "avg_on_minus_off": sum(deltas) / len(deltas)}
        for domain, deltas in sorted(domain_deltas.items())
    }
    all_deltas = [s["delta"] for s in per_scenario]
    return {
        "per_scenario": sorted(per_scenario, key=lambda s: (s["domain"], s["id"])),
        "per_domain": per_domain,
        "overall_avg_on_minus_off": (
            sum(all_deltas) / len(all_deltas) if all_deltas else 0.0
        ),
        "n_compared": len(per_scenario),
        "n_skipped": len(skipped),
        "skipped_ids": sorted(skipped),
    }


def format_report(report: dict[str, Any]) -> str:
    """Render a :func:`build_report` result as a readable text table."""
    lines = [
        "RAG ablation — builtin knowledge ON vs OFF (judge `overall`, 1-5)",
        "delta = ON - OFF  (positive => builtin RAG helped)",
        "",
        f"{'domain':<16}{'n':>4}{'avg delta':>14}",
        f"{'-' * 16}{'-' * 4}{'-' * 14}",
    ]
    for domain, agg in report["per_domain"].items():
        lines.append(f"{domain:<16}{agg['n']:>4}{agg['avg_on_minus_off']:>14.2f}")
    lines.append(f"{'-' * 16}{'-' * 4}{'-' * 14}")
    lines.append(
        f"{'ALL':<16}{report['n_compared']:>4}"
        f"{report['overall_avg_on_minus_off']:>14.2f}"
    )
    if report["n_skipped"]:
        lines.append("")
        lines.append(
            f"skipped {report['n_skipped']} scenario(s) that errored in one arm: "
            + ", ".join(report["skipped_ids"])
        )
    return "\n".join(lines)


async def _collect_scores(kind: str, scenario_id: str | None) -> dict[str, float | None]:
    """Run the suite once and return ``{scenario_id: overall_score | None}``.

    ``None`` marks a scenario that errored (so it can be excluded from the diff
    rather than counted as a zero).
    """
    from openexecutive.evals.runner import run_scenarios

    scores: dict[str, float | None] = {}
    async for ev in run_scenarios(kind=kind, scenario_id=scenario_id):
        if ev["type"] == "scenario_done":
            scores[ev["scenario_id"]] = float(ev["scores"].get("overall", 0) or 0)
        elif ev["type"] == "scenario_error":
            scores[ev["scenario_id"]] = None
    return scores


async def run_ablation(
    kind: str = "chat", scenario_id: str | None = None
) -> dict[str, Any]:
    """Run the suite with builtin RAG on, then off, and diff per domain.

    Makes ~2x the normal suite's paid LLM calls. The two arms run
    sequentially (never concurrently) because the off arm mutates a
    process-global env var; overlapping them would race the toggle.
    """
    from openexecutive.evals.scenarios import load_scenarios

    id_to_domain = {
        s["id"]: s.get("domain", "")
        for s in load_scenarios(kind=kind, scenario_id=scenario_id)
    }

    on_scores = await _collect_scores(kind, scenario_id)

    prior = os.environ.get(_BUILTIN_N_ENV)
    os.environ[_BUILTIN_N_ENV] = "0"
    try:
        off_scores = await _collect_scores(kind, scenario_id)
    finally:
        # Restore exactly — including absence — so the harness leaves no trace.
        if prior is None:
            os.environ.pop(_BUILTIN_N_ENV, None)
        else:
            os.environ[_BUILTIN_N_ENV] = prior

    return build_report(id_to_domain, on_scores, off_scores)


def main() -> None:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="RAG ablation: builtin knowledge on vs off (makes ~2x paid eval calls)."
    )
    parser.add_argument("--kind", default="chat", help="scenario kind (default: chat)")
    parser.add_argument("--scenario", default=None, help="single scenario id (optional)")
    args = parser.parse_args()

    report = asyncio.run(run_ablation(kind=args.kind, scenario_id=args.scenario))
    print(format_report(report))


if __name__ == "__main__":
    main()
