"""Insert-time validation + normalization of watchlist targets.

The watchlist is largely populated by an LLM (the ``executive_research``
workflow) proposing ``rss`` feed URLs it never verified — historically
the great majority were dead (404 / 403 / not-actually-a-feed), producing
a watchlist full of rows that fetch nothing and a permanently-empty
briefing.

This module validates an ``rss`` target at insert time: it must fetch and
parse as a feed with entries. A target the server *answers* but that
isn't a feed is either:

  - converted to a scrape-backed ``page_watch`` when xcrawl can read the
    page (modern JS / bot-blocked news pages publish no feed), or
  - rejected (:class:`WatchlistTargetError`),

so a dead ``rss`` row never reaches the scan loop. A transient / network
blip passes the target through unchanged rather than blocking a
legitimate add on a hiccup. Every non-``rss`` type returns unchanged with
no network I/O.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import feedparser
import httpx

from openexecutive.config import get_settings
from openexecutive.monitoring.models import (
    PAGE_WATCH_FETCH_KEY,
    PAGE_WATCH_FETCH_XCRAWL,
    SOURCE_KIND_PAGE_WATCH,
    SOURCE_KIND_RSS,
)
from openexecutive.monitoring.sources._http import (
    FetchOverflowError,
    fetch_bounded,
    validate_target_url,
)

logger = logging.getLogger(__name__)


class WatchlistTargetError(Exception):
    """A watchlist target failed insert-time validation (definitively bad)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def validate_and_normalize_target(
    signal_type: str, target: str, config: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Validate ``target`` for ``signal_type``; may convert the signal type.

    Returns the ``(signal_type, target, config)`` to insert — converted to
    ``page_watch`` when a non-feed ``rss`` target is scrapeable. Raises
    :class:`WatchlistTargetError` when an ``rss`` target is definitively
    bad and can't be salvaged. Only ``rss`` is validated; every other type
    is returned unchanged with no network I/O.
    """
    if signal_type != SOURCE_KIND_RSS:
        return signal_type, target, config

    verdict = await _feed_check(target)
    if verdict == "feed":
        return signal_type, target, config
    if verdict == "unknown":
        # Transient fetch failure — inserting as-is beats rejecting a feed
        # that's merely unreachable right now; the scan loop retries.
        logger.info(
            "watchlist validate: %r unreachable now — inserting rss unverified",
            target,
        )
        return signal_type, target, config
    if verdict == "blocked":
        # SSRF-rejected / unparseable / non-public. Reject outright — do NOT
        # offer the xcrawl-scrape conversion, which would fetch the target
        # from xcrawl's network and bypass our SSRF guard.
        raise WatchlistTargetError(
            f"{target!r} is not a fetchable public URL "
            "(blocked by the SSRF guard or unparseable)."
        )

    # verdict == "not_feed": a public server answered, but it is not a feed.
    from openexecutive.integrations import xcrawl_client

    if await xcrawl_client.scrape(target) is not None:
        new_config = dict(config)
        new_config[PAGE_WATCH_FETCH_KEY] = PAGE_WATCH_FETCH_XCRAWL
        # page_watch reads config["label"]; the rss row used "feed_label".
        label = new_config.pop("feed_label", None)
        if label and "label" not in new_config:
            new_config["label"] = label
        logger.info(
            "watchlist validate: %r is not a feed but is scrapeable — "
            "converting rss → page_watch (xcrawl)", target,
        )
        return SOURCE_KIND_PAGE_WATCH, target, new_config

    raise WatchlistTargetError(
        f"{target!r} is not a valid RSS/Atom feed and could not be scraped. "
        "Fix the feed URL, or add it as signal_type='page_watch'."
    )


async def _feed_check(
    target: str,
) -> Literal["feed", "not_feed", "blocked", "unknown"]:
    """Classify ``target``.

    ``feed`` — feedparser recognized it as a feed.
    ``not_feed`` — a public server answered, but it isn't a feed.
    ``blocked`` — SSRF-rejected / unparseable / non-public URL (never fetched).
    ``unknown`` — transient fetch failure; caller should not penalize it.
    """
    ok, _reason = validate_target_url(target)
    if not ok:
        return "blocked"
    max_bytes = get_settings().external_monitor_max_fetch_bytes
    try:
        body = await fetch_bounded(target, max_bytes)
    except FetchOverflowError:
        return "not_feed"  # too big to be a sane feed
    except httpx.HTTPStatusError:
        return "not_feed"  # server answered 4xx/5xx → definitively bad
    except (httpx.HTTPError, httpx.InvalidURL):
        return "unknown"   # connection / timeout — transient
    # feedparser sets `version` (e.g. "rss20", "atom10") for anything it
    # recognizes as a feed — INCLUDING a valid but currently-empty feed. Use
    # it rather than `.entries` so a brand-new / quiet feed isn't misread as a
    # non-feed page and wrongly converted or rejected. Use dict `.get` (not
    # attribute access): an empty body yields a FeedParserDict with no
    # `version` key at all, and `parsed.version` would AttributeError.
    parsed = feedparser.parse(body)
    return "feed" if parsed.get("version") else "not_feed"


__all__ = ["WatchlistTargetError", "validate_and_normalize_target"]
