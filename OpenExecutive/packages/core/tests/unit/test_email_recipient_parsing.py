"""Tests for email_poller._parse_recipients.

Exercises the To+Cc header walker the multi-peer wire-up uses to
enumerate distinct recipients. Mirrors _strip_reply_to's existing
header-only behaviour: stops at first blank line, honours folded
continuations, returns deduped lowercase addresses.
"""
from __future__ import annotations

from openexecutive.integrations.email_poller import _parse_recipients


def test_extracts_bare_addresses_from_to_header() -> None:
    raw = "From: alice@example.com\nTo: bob@example.com\nSubject: hi\n\nbody"
    assert _parse_recipients(raw) == ["bob@example.com"]


def test_extracts_addresses_from_name_angle_format() -> None:
    raw = (
        "From: alice@example.com\n"
        "To: Bob Smith <bob@example.com>, \"Carol Q\" <carol@example.com>\n"
        "\n"
        "body"
    )
    assert _parse_recipients(raw) == ["bob@example.com", "carol@example.com"]


def test_combines_to_and_cc() -> None:
    raw = (
        "To: bob@example.com\n"
        "Cc: carol@example.com, dave@example.com\n"
        "\n"
        "body"
    )
    assert _parse_recipients(raw) == [
        "bob@example.com",
        "carol@example.com",
        "dave@example.com",
    ]


def test_honours_folded_continuation_lines() -> None:
    # RFC 5322 allows headers to be split across lines if continuation
    # lines start with whitespace. The parser must concatenate them.
    raw = (
        "To: bob@example.com,\n"
        " carol@example.com,\n"
        "\tdave@example.com\n"
        "\n"
        "body"
    )
    assert _parse_recipients(raw) == [
        "bob@example.com",
        "carol@example.com",
        "dave@example.com",
    ]


def test_deduplicates_case_insensitive() -> None:
    raw = (
        "To: Bob@Example.com, bob@example.com\n"
        "Cc: BOB@EXAMPLE.COM\n"
        "\n"
        "body"
    )
    assert _parse_recipients(raw) == ["bob@example.com"]


def test_stops_at_header_body_boundary() -> None:
    """The body might contain `To:` or `Cc:` lines that aren't headers —
    they must NOT be parsed as recipients."""
    raw = (
        "From: alice@example.com\n"
        "To: bob@example.com\n"
        "\n"
        "Cc: not-a-recipient@spoofed.com\n"
        "Reply to this email and add Bob.\n"
    )
    assert _parse_recipients(raw) == ["bob@example.com"]


def test_empty_or_missing_headers_return_empty_list() -> None:
    assert _parse_recipients("") == []
    assert _parse_recipients("Subject: hello\n\nbody") == []
    assert _parse_recipients("From: alice@example.com\n\nbody") == []


def test_no_blank_line_still_parses_present_headers() -> None:
    """A truncated raw email (no body, no terminating blank line) should
    still parse the headers we DID see."""
    raw = "To: bob@example.com\nCc: carol@example.com"
    assert _parse_recipients(raw) == ["bob@example.com", "carol@example.com"]


def test_ignores_other_headers() -> None:
    raw = (
        "From: alice@example.com\n"
        "To: bob@example.com\n"
        "Reply-To: malicious@attacker.com\n"
        "Subject: hi\n"
        "\n"
        "body"
    )
    # Only To/Cc count — From and Reply-To are NOT included even though
    # they contain valid email addresses.
    assert _parse_recipients(raw) == ["bob@example.com"]
