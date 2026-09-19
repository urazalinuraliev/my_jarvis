"""Unit tests for the post-dedup research finding verification pass.

Network (xcrawl scrape) and the verify LLM call are both mocked — these
tests exercise selection/cap/gating and the verdict→confidence mapping.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openexecutive.alerts.models import AlertSeverity
from openexecutive.monitoring.research import verification as v
from openexecutive.monitoring.research.models import ResearchFinding


def _finding(
    *,
    title: str = "T",
    confidence: str = "high",
    severity: AlertSeverity = AlertSeverity.MEDIUM,
    urls: list[str] | None = None,
) -> ResearchFinding:
    return ResearchFinding(
        title=title,
        summary=f"summary for {title}",
        severity_hint=severity,
        confidence=confidence,  # type: ignore[arg-type]
        relevant_urls=urls if urls is not None else ["https://src.example/a"],
    )


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    monkeypatch.setenv("XCRAWL_API_KEY", "dummy")  # mocked; never used live
    monkeypatch.setenv("EXTERNAL_RESEARCH_VERIFY_ENABLED", "true")


def _mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scrape: str | None = "page text",
    scrape_status: str | None = None,
    verdicts: dict[str, str] | None = None,
    verdict_raises: bool = False,
) -> None:
    """Mock the xcrawl scrape AND the verify model's provider call (one level
    below _llm_verdict), so the real _verify_one → _llm_verdict →
    _parse_verdict → confidence-mapping path is exercised. ``verdicts`` maps a
    finding title to the verdict the model 'returns'; the sentinel 'no_tool'
    makes the model return a text-only message (→ parsed as 'unknown').
    ``scrape_status`` overrides the ScrapeOutcome status (defaults: a string
    body → 'ok', None → 'empty'); pass 'error' to simulate an xcrawl infra
    failure."""
    status = scrape_status or ("ok" if scrape is not None else "empty")

    async def fake_scrape_detailed(url: str) -> Any:
        return v.xcrawl_client.ScrapeOutcome(scrape, status)  # type: ignore[arg-type]

    async def fake_analyze(self: Any, user_content: str, **kwargs: Any) -> Any:
        if verdict_raises:
            raise RuntimeError("provider boom")
        verdict = "confirmed"
        for title, vd in (verdicts or {}).items():
            if f"TITLE: {title}" in user_content:
                verdict = vd
                break
        if verdict == "no_tool":
            return SimpleNamespace(content=[SimpleNamespace(type="text")])
        return SimpleNamespace(content=[
            SimpleNamespace(
                type="tool_use", name="emit_verification",
                input={"verdict": verdict},
            ),
        ])

    monkeypatch.setattr(v.xcrawl_client, "scrape_detailed", fake_scrape_detailed)
    monkeypatch.setattr(v._VerifyAgent, "analyze_with_tools", fake_analyze)


# --------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_verify_disabled_is_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "true")
    monkeypatch.setenv("XCRAWL_API_KEY", "dummy")
    monkeypatch.setenv("EXTERNAL_RESEARCH_VERIFY_ENABLED", "false")

    async def boom_scrape(url: str) -> Any:
        raise AssertionError("must not scrape when verification disabled")

    monkeypatch.setattr(v.xcrawl_client, "scrape_detailed", boom_scrape)
    findings = [_finding()]
    out = await v.verify_findings(findings)
    assert out is findings  # unchanged, no work


@pytest.mark.asyncio
async def test_xcrawl_disabled_is_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCRAWL_ENABLED", "false")
    monkeypatch.setenv("EXTERNAL_RESEARCH_VERIFY_ENABLED", "true")
    out = await v.verify_findings([_finding()])
    assert out[0].verification is None


# --------------------------------------------------------------------- #
# Verdict → confidence mapping
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_confirmed_keeps_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    _mock(monkeypatch, verdicts={"T": "confirmed"})
    out = await v.verify_findings([_finding(confidence="medium")])
    assert out[0].confidence == "medium"
    assert out[0].verification == "confirmed"


@pytest.mark.asyncio
async def test_contradicted_sets_low(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    _mock(monkeypatch, verdicts={"T": "contradicted"})
    out = await v.verify_findings([_finding(confidence="high")])
    assert out[0].confidence == "low"
    assert out[0].verification == "contradicted"


@pytest.mark.asyncio
async def test_unsupported_demotes_one_notch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    _mock(monkeypatch, verdicts={"T": "unsupported"})
    out = await v.verify_findings([_finding(confidence="high")])
    assert out[0].confidence == "medium"
    assert out[0].verification == "unsupported"


@pytest.mark.asyncio
async def test_empty_page_is_source_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fetched OK but no content → genuinely dead/unreadable URL → demote.
    _enable(monkeypatch)
    _mock(monkeypatch, scrape=None, scrape_status="empty")
    out = await v.verify_findings([_finding(confidence="medium")])
    assert out[0].confidence == "low"
    assert out[0].verification == "source_unreachable"


@pytest.mark.asyncio
async def test_scrape_infra_error_leaves_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # xcrawl itself failed (down / 401 / 429 / timeout) — NOT a verdict on the
    # source. A verify-pass outage must never demote a real finding.
    _enable(monkeypatch)
    _mock(monkeypatch, scrape=None, scrape_status="error")
    out = await v.verify_findings([_finding(confidence="medium")])
    assert out[0].confidence == "medium"  # untouched
    assert out[0].verification is None  # not tagged — we couldn't check


@pytest.mark.asyncio
async def test_scrape_disabled_leaves_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # XCRAWL_ENABLED=true but no key → scrape_detailed returns "disabled". The
    # verify_findings gate only checks the enabled flag, so this reaches
    # _verify_one — a config gap must not demote a real finding.
    _enable(monkeypatch)
    _mock(monkeypatch, scrape=None, scrape_status="disabled")
    out = await v.verify_findings([_finding(confidence="medium")])
    assert out[0].confidence == "medium"  # untouched
    assert out[0].verification is None


@pytest.mark.asyncio
async def test_unknown_verdict_keeps_confidence_tags_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Model returned no usable tool verdict → 'unknown' → confidence untouched,
    # but tagged so the run's verified-count reflects the attempt.
    _enable(monkeypatch)
    _mock(monkeypatch, verdicts={"T": "no_tool"})
    out = await v.verify_findings([_finding(confidence="high")])
    assert out[0].confidence == "high"
    assert out[0].verification == "inconclusive"


@pytest.mark.asyncio
async def test_verify_failure_leaves_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    _mock(monkeypatch, verdict_raises=True)
    out = await v.verify_findings([_finding(confidence="high")])
    assert out[0].confidence == "high"
    assert out[0].verification is None


# --------------------------------------------------------------------- #
# Selection / cap
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_no_url_finding_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)

    async def boom_scrape(url: str) -> Any:
        raise AssertionError("no cited URL → must not scrape")

    monkeypatch.setattr(v.xcrawl_client, "scrape_detailed", boom_scrape)
    out = await v.verify_findings([_finding(urls=[])])
    assert out[0].verification is None


@pytest.mark.asyncio
async def test_low_confidence_finding_is_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A finding already at 'low' is dropped by the downstream filter anyway —
    # don't spend a scrape/LLM on it, and don't let it skew the accounting.
    _enable(monkeypatch)

    async def boom_scrape(url: str) -> Any:
        raise AssertionError("low-confidence finding must not be verified")

    monkeypatch.setattr(v.xcrawl_client, "scrape_detailed", boom_scrape)
    out = await v.verify_findings([_finding(confidence="low")])
    assert out[0].verification is None


@pytest.mark.asyncio
async def test_cap_verifies_highest_severity_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv("RESEARCH_VERIFY_MAX_FINDINGS", "1")
    _mock(monkeypatch, verdicts={"low-sev": "unsupported", "urgent-sev": "unsupported"})
    findings = [
        _finding(title="low-sev", severity=AlertSeverity.LOW, confidence="high"),
        _finding(title="urgent-sev", severity=AlertSeverity.URGENT, confidence="high"),
    ]
    out = await v.verify_findings(findings)
    verified = [f for f in out if f.verification is not None]
    assert len(verified) == 1
    assert verified[0].title == "urgent-sev"  # highest severity got the budget


# --------------------------------------------------------------------- #
# _parse_verdict + helpers
# --------------------------------------------------------------------- #

def _msg(blocks: list[Any]) -> Any:
    return SimpleNamespace(content=blocks)


def _tool_block(name: str, inp: dict) -> Any:
    return SimpleNamespace(type="tool_use", name=name, input=inp)


def test_parse_verdict_reads_tool_use() -> None:
    for verdict in ("confirmed", "contradicted", "unsupported"):
        msg = _msg([_tool_block("emit_verification", {"verdict": verdict})])
        assert v._parse_verdict(msg) == verdict


def test_parse_verdict_unknown_when_missing_or_bad() -> None:
    assert v._parse_verdict(_msg([])) == "unknown"
    assert v._parse_verdict(_msg([SimpleNamespace(type="text")])) == "unknown"
    assert v._parse_verdict(
        _msg([_tool_block("emit_verification", {"verdict": "maybe"})])
    ) == "unknown"
    assert v._parse_verdict(
        _msg([_tool_block("other_tool", {"verdict": "confirmed"})])
    ) == "unknown"


def test_demote_and_first_url() -> None:
    assert v._demote("high") == "medium"
    assert v._demote("medium") == "low"
    assert v._demote("low") == "low"
    assert v._first_url(_finding(urls=["not-a-url", "https://ok.example/x"])) == \
        "https://ok.example/x"
    assert v._first_url(_finding(urls=["ftp://x", "mailto:y"])) is None
