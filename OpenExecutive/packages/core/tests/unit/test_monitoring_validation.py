"""Unit tests for the shared watchlist validators in monitoring/validation.py.

Both the chat tool (orchestrator/watchlist_tools.py) and the HTTP route
(api/routes/watchlist.py) call into this module — the tests below make
sure the two surfaces can't drift on slug rules or severity values.
"""
from __future__ import annotations

from openexecutive.alerts.models import AlertSeverity
from openexecutive.monitoring.validation import (
    VALID_SEVERITY_VALUES,
    WATCHLIST_SLUG_RE,
    is_valid_severity,
    is_valid_watchlist_slug,
)


def test_valid_slugs_accepted() -> None:
    assert is_valid_watchlist_slug("stock-aapl")
    assert is_valid_watchlist_slug("vendor-aws")
    assert is_valid_watchlist_slug("rss-acme-changelog")
    assert is_valid_watchlist_slug("a")
    assert is_valid_watchlist_slug("a" + "-" * 60)  # 61 chars total, at boundary


def test_uppercase_and_whitespace_rejected() -> None:
    assert not is_valid_watchlist_slug("Stock-AAPL")
    assert not is_valid_watchlist_slug("stock aapl")
    assert not is_valid_watchlist_slug(" stock-aapl")
    assert not is_valid_watchlist_slug("stock-aapl\n")


def test_leading_hyphen_rejected() -> None:
    # Cosmetic — kebab-case slugs that start with a hyphen look broken in audit text.
    assert not is_valid_watchlist_slug("-stock-aapl")


def test_overlong_slug_rejected() -> None:
    assert not is_valid_watchlist_slug("a" * 62)  # 62 chars, one past the limit


def test_unicode_and_control_chars_rejected() -> None:
    # Reject RTL overrides and control codes — they show up in audit
    # text and can be used to spoof other slugs.
    assert not is_valid_watchlist_slug("stock‮aapl")
    assert not is_valid_watchlist_slug("stock\x00aapl")  # NUL byte
    assert not is_valid_watchlist_slug("stôck-aapl")


def test_severity_set_matches_enum() -> None:
    # If a new AlertSeverity ships, this test fires so the validator is
    # updated in lockstep — otherwise the HTTP route would silently
    # reject a level the alert pipeline accepts.
    assert frozenset(s.value for s in AlertSeverity) == VALID_SEVERITY_VALUES


def test_is_valid_severity_matches_set() -> None:
    for s in AlertSeverity:
        assert is_valid_severity(s.value)
    assert not is_valid_severity("catastrophic")
    assert not is_valid_severity("")


def test_regex_object_exported() -> None:
    # Other modules may want the pattern itself for error-message
    # formatting; make sure the export is the compiled regex.
    assert WATCHLIST_SLUG_RE.match("stock-aapl") is not None
    assert WATCHLIST_SLUG_RE.match("STOCK") is None
