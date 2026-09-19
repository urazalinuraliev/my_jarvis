"""Unit tests for openexecutive.briefing.ranking."""
from __future__ import annotations

import pytest

from openexecutive.briefing import ranking


def test_unrouted_low_external_is_monitoring() -> None:
    assert ranking.categorize(
        source="stock", severity="low", routed_to_person_id=None,
        topic_tags=["external:stock-aapl"],
    ) == "monitoring"


def test_routed_external_is_action() -> None:
    # A human/triage explicitly routed it — never hide it.
    assert ranking.categorize(
        source="stock", severity="low", routed_to_person_id=42,
        topic_tags=["external:stock-aapl"],
    ) == "action"


def test_high_severity_external_is_action() -> None:
    assert ranking.categorize(
        source="stock", severity="high", routed_to_person_id=None,
        topic_tags=["external:stock-aapl"],
    ) == "action"


def test_non_external_unrouted_is_action() -> None:
    # Triage-classified inbound is not passive monitoring even when unrouted.
    assert ranking.categorize(
        source="triage", severity="low", routed_to_person_id=None,
        topic_tags=["department:finance"],
    ) == "action"


def test_external_tag_without_known_source_still_monitoring() -> None:
    assert ranking.categorize(
        source="custom", severity="medium", routed_to_person_id=None,
        topic_tags=["external:rss-techcrunch"],
    ) == "monitoring"


@pytest.mark.parametrize("source", ["query", "edgar", "page_watch"])
def test_newer_adapter_sources_are_external_monitoring(source: str) -> None:
    # Regression: the query/edgar/page_watch adapters were added after this
    # module last shipped, so their unrouted low/medium signals fell through to
    # "action" and never reached the Monitoring lane. They must categorize as
    # monitoring on the source alone (no external:* tag required).
    assert ranking.categorize(
        source=source, severity="medium", routed_to_person_id=None,
        topic_tags=["finance"],
    ) == "monitoring"


@pytest.mark.parametrize("source", ["query", "edgar", "page_watch"])
def test_newer_adapter_high_severity_still_action(source: str) -> None:
    # A high-severity hit from a passive source is still an escalation.
    assert ranking.categorize(
        source=source, severity="high", routed_to_person_id=None,
        topic_tags=["finance"],
    ) == "action"


def test_external_sources_covers_every_registered_adapter() -> None:
    # Sync guard against drift: `_EXTERNAL_SOURCES` duplicates the adapter
    # source kinds (canonical home: monitoring/models.py SOURCE_KIND_*). Assert
    # against the runtime registry so adding an adapter without listing it here
    # — which silently drops its low/medium signals into "action" — fails.
    from openexecutive.monitoring.sources import _REGISTRY

    assert _REGISTRY, "expected the source adapter registry to be populated"
    missing = set(_REGISTRY) - ranking._EXTERNAL_SOURCES
    assert not missing, f"_EXTERNAL_SOURCES omits registered adapter(s): {sorted(missing)}"


def test_score_severity_ordering() -> None:
    s = lambda sev: ranking.score(severity=sev, routed_to_person_id=None)  # noqa: E731
    assert s("urgent") > s("high") > s("medium") > s("low")


def test_score_routed_bonus() -> None:
    base = ranking.score(severity="medium", routed_to_person_id=None)
    routed = ranking.score(severity="medium", routed_to_person_id=7)
    assert routed == base + 15


def test_unknown_severity_falls_back_to_medium_band() -> None:
    assert ranking.score(severity="bogus", routed_to_person_id=None) == ranking.score(
        severity="medium", routed_to_person_id=None
    )


def test_score_and_categorize_accepts_dict_and_object() -> None:
    as_dict = {
        "source": "stock", "severity": "low",
        "routed_to_person_id": None, "topic_tags": ["external:stock-x"],
    }
    score_d, cat_d, reason_d = ranking.score_and_categorize(as_dict)

    class _Alert:
        source = "stock"
        severity = "low"
        routed_to_person_id = None
        topic_tags = ["external:stock-x"]

    score_o, cat_o, reason_o = ranking.score_and_categorize(_Alert())
    assert (score_d, cat_d, reason_d) == (score_o, cat_o, reason_o)
    assert (score_d, cat_d, reason_d) == (10, "monitoring", None)


def test_surfaced_reason_high_external_unrouted() -> None:
    reason = ranking.surfaced_reason(
        source="stock", severity="high", routed_to_person_id=None,
        topic_tags=["external:stock-rivn"],
    )
    assert reason and "Monitoring" in reason


def test_surfaced_reason_urgent_external_unrouted() -> None:
    reason = ranking.surfaced_reason(
        source="stock", severity="urgent", routed_to_person_id=None,
        topic_tags=["external:stock-rivn"],
    )
    assert reason and "Monitoring" in reason


def test_surfaced_reason_low_external_is_none() -> None:
    # Already sits in Monitoring — nothing to explain.
    assert ranking.surfaced_reason(
        source="stock", severity="medium", routed_to_person_id=None,
        topic_tags=["external:stock-rivn"],
    ) is None


def test_surfaced_reason_routed_is_none() -> None:
    # Routed items are in "action" because a human chose so, not severity.
    assert ranking.surfaced_reason(
        source="stock", severity="high", routed_to_person_id=42,
        topic_tags=["external:stock-rivn"],
    ) is None


def test_surfaced_reason_non_external_is_none() -> None:
    assert ranking.surfaced_reason(
        source="triage", severity="high", routed_to_person_id=None,
        topic_tags=["department:finance"],
    ) is None


def test_surfaced_reason_aligns_with_categorize() -> None:
    # Invariant: a reason is present only when the item is external AND in
    # the action lane — i.e. categorize == "action" for an external signal.
    args = dict(
        source="stock", severity="high", routed_to_person_id=None,
        topic_tags=["external:stock-rivn"],
    )
    assert ranking.categorize(**args) == "action"
    assert ranking.surfaced_reason(**args) is not None
