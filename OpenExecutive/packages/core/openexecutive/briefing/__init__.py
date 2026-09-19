"""Briefing presentation helpers.

Turns the raw `/today` snapshot into something that tells a story:
  - `ranking` — score + categorize proposals so genuinely-actionable items
    lead and low-signal monitoring noise can be demoted.
  - `narrative` — the shared Executive-voice synthesizer used by both the
    morning-brief DM and the on-page briefing header.
  - `narrative_cache` — on-disk cache for the page narrative so it is served
    instantly and regenerated off the request hot path.
"""
