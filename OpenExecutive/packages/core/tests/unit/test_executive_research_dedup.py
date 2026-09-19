"""Unit tests for the cross-specialist finding dedup."""
from __future__ import annotations

from openexecutive.alerts.models import AlertSeverity
from openexecutive.monitoring.research.dedup import dedup_findings
from openexecutive.monitoring.research.models import ResearchFinding


def _f(
    *,
    title: str = "Title",
    summary: str = "Summary " * 5,
    severity: AlertSeverity = AlertSeverity.MEDIUM,
    confidence: str = "medium",
) -> ResearchFinding:
    return ResearchFinding(
        title=title,
        summary=summary,
        severity_hint=severity,
        suggested_audience="principal",
        confidence=confidence,
    )


def test_dedup_collapses_identical_title_and_summary_prefix() -> None:
    a = _f(title="Acme raised $50M Series C")
    b = _f(title="Acme raised $50M Series C")
    out = dedup_findings({"cso": [a], "cfo": [b]})
    assert len(out) == 1


def test_dedup_attributes_multiple_specialists() -> None:
    a = _f(title="Acme raised $50M")
    b = _f(title="Acme raised $50M")
    out = dedup_findings({"cso": [a], "cfo": [b]})
    assert len(out) == 1
    # First specialist stamps; second's slug appears via the
    # source_specialist attribution.
    assert "cso" in out[0].source_specialist
    assert "cfo" in out[0].source_specialist


def test_dedup_promotes_severity_to_max() -> None:
    a = _f(title="t", severity=AlertSeverity.MEDIUM)
    b = _f(title="t", severity=AlertSeverity.URGENT)
    out = dedup_findings({"cso": [a], "cfo": [b]})
    assert out[0].severity_hint == AlertSeverity.URGENT


def test_dedup_promotes_confidence_to_max() -> None:
    a = _f(title="t", confidence="low")
    b = _f(title="t", confidence="high")
    out = dedup_findings({"cso": [a], "cfo": [b]})
    assert out[0].confidence == "high"


def test_dedup_keeps_distinct_titles_separate() -> None:
    a = _f(title="Apple stock down 7%")
    b = _f(title="Microsoft stock up 3%")
    out = dedup_findings({"cfo": [a, b]})
    assert len(out) == 2


def test_dedup_empty_input_returns_empty() -> None:
    assert dedup_findings({}) == []
    assert dedup_findings({"cso": []}) == []
