"""Per-specialist research prompts.

Each specialist gets their normal chat-time persona PLUS a research-mode
addendum that:
  (a) names the task — surface findings via ``emit_research_findings``,
  (b) constrains the domain — only the kinds of external signals this
      specialist owns,
  (c) reminds them to use web_search to find RECENT developments and
      verify URLs / dates / facts (not just generate them from training
      data, which is stale by construction), and
  (d) explicitly clarifies the Executive — not the specialist — does
      the routing, so they don't try to send messages themselves.
"""
from __future__ import annotations

# Hard cap per specialist. Empirically 8 was too generous — 7 specs
# × 8 produced ~52 candidate findings per run, far more than the
# Executive could meaningfully route. 3 forces the specialist to pick
# the few items that are actually material to THIS company.
PER_SPECIALIST_FINDING_CAP = 3


def shared_research_addendum() -> str:
    """Task framing every specialist gets appended to their normal prompt."""
    addendum = (
        "\n\n---\n"
        "## TASK: RESEARCH FINDINGS\n"
        "\n"
        "You are NOT answering a user question. You are researching "
        "what's specifically actionable for THIS company in your "
        "domain. The Executive routes findings; you do NOT send "
        "messages yourself.\n"
        "\n"
        f"**Aim for 1–{PER_SPECIALIST_FINDING_CAP} findings.** Search "
        "your domain actively before concluding there's nothing — "
        "there is almost always some recent, relevant movement worth "
        "surfacing. Emit every item that genuinely clears the grounding "
        "+ recency + actionability bars below, up to the cap of "
        f"{PER_SPECIALIST_FINDING_CAP}; surfacing is cheap because the "
        "Executive does a second, stricter pass before anything reaches "
        "a human. Zero is acceptable ONLY when an active search turned "
        "up nothing recent and relevant — not as a default. Do not pad "
        "with weak items to hit the cap; quality still gates each one.\n"
        "\n"
        "## REQUIRED GROUNDING\n"
        "\n"
        "Every finding MUST name at least one of these from the company "
        "context provided in this turn, BY NAME, in the summary:\n"
        "  - a primary competitor from `competitive_landscape.primary_competitors`\n"
        "  - an active initiative from the ACTIVE INITIATIVES list\n"
        "  - a strategic priority from `strategic_priorities.current_year`\n"
        "  - a vendor / dependency named in the profile or directly "
        "implied by the stack (e.g. 'Stripe' for a SaaS company)\n"
        "  - a tracked ticker (own or competitor) — for stock moves\n"
        "\n"
        "If you cannot reference one of these by name, DO NOT emit the "
        "finding. 'Industry trend' / 'sector news' / 'general "
        "regulatory shift' findings are NEVER acceptable.\n"
        "\n"
        "## REQUIRED ACTIONABILITY\n"
        "\n"
        "Every finding's `suggested_action` must be a verifiable step "
        "a specific human can complete in under 15 minutes (open a "
        "status page, refresh a battlecard, ping a vendor, update a "
        "competitive doc). 'Monitor the situation' / 'stay aware' / "
        "'consider impact' are NOT actionable — drop the finding if "
        "that's all you can suggest.\n"
        "\n"
        "## REQUIRED RECENCY\n"
        "\n"
        "This is a scan for what changed RECENTLY — not a textbook "
        "recap. Every finding must describe a specific development from "
        "roughly the last 30 days (fresher is better). Use web_search "
        "to FIND it and to confirm its date; cite the dated source — a "
        "URL in `relevant_urls`, or a specific dated source named in "
        "the summary — and reference the timeframe in the summary "
        "(e.g. 'on <date>', 'this week', 'in their Q2 release').\n"
        "\n"
        "Do NOT emit findings from memory / training knowledge — they "
        "are stale by construction and usually wrong on current facts. "
        "If web_search is unavailable, or it returns nothing genuinely "
        "recent for an item, DROP that item: emitting ZERO findings is "
        "far better than emitting an old or unverifiable one. An "
        "undated, evergreen, or 'as of my last knowledge' finding is "
        "never acceptable.\n"
        "\n"
        "## VERIFICATION\n"
        "\n"
        "USE web_search to verify URLs, dates, names, and numbers — do "
        "not emit facts you can't verify against a current source. "
        "Prefer findings backed by a dated URL you actually retrieved. "
        "A finding with no verifiable recent source named in the "
        "summary (e.g. a specific dated filing, a quoted earnings "
        "remark) must be dropped — never emit on vibes.\n"
        "\n"
        "## OUTPUT\n"
        "\n"
        "Emit via the `emit_research_findings` tool — do not narrate. "
        "Each finding needs:\n"
        "  - title — short headline, no period\n"
        "  - summary — 1-3 sentences. MUST name a competitor / "
        "initiative / priority / vendor / ticker from the context.\n"
        "  - severity_hint — low / medium / high / urgent. Default "
        "medium. 'urgent' only when action is needed within 24h.\n"
        "  - suggested_audience — soft hint the Executive may override:\n"
        "      'principal' — ONLY for material, principal-only matters\n"
        "      'department:<slug>' — preferred for most tactical items\n"
        "      'watchlist' — when worth ONGOING monitoring (rare)\n"
        "      'workflow:<name>' — when warranting deeper analysis\n"
        "      'noone' — log only (Executive will likely ignore)\n"
        "  - suggested_action — verifiable next step <15 min\n"
        "  - relevant_urls — URLs you verified\n"
        "  - confidence — high / medium / low. **'low' findings are "
        "DROPPED by the workflow before the Executive sees them** — do "
        "not emit a finding you would not stake 'medium' on."
    )
    return addendum + _read_before_cite_addendum()


def _read_before_cite_addendum() -> str:
    """Extra contract that only applies when the agentic scrape loop is on:
    the specialist has a ``scrape_url`` tool and MUST read sources before
    citing. Empty otherwise so the prompt always matches the available
    tools. Static per-deployment (the flag is constant in-process), so it
    does not break the cached system block.
    """
    from openexecutive.config import get_settings

    if not get_settings().research_agentic_scrape_enabled:
        return ""
    return (
        "\n\n## READ BEFORE YOU CITE\n"
        "\n"
        "You have a `scrape_url` tool. web_search returns SNIPPETS — they "
        "are NOT enough to cite. Before emitting ANY finding:\n"
        "  1. Use web_search to find candidate sources.\n"
        "  2. Call `scrape_url` on the 1-3 most promising results to READ "
        "the full article.\n"
        "  3. Ground every number / date / quote in the finding's summary "
        "in what the scraped page ACTUALLY says.\n"
        "  4. In `relevant_urls`, cite the specific ARTICLE url you "
        "scraped and read — never a homepage or section link, and never a "
        "page you did not read.\n"
        "\n"
        "**This is enforced, not advisory: if you call "
        "`emit_research_findings` before scraping at least one source, the "
        "emit is REJECTED and you are sent back to scrape first.** So always "
        "`scrape_url` at least one source before you emit. A finding whose "
        "source you did not scrape + read will also be demoted or dropped by "
        "the verification pass. When you have read enough, call "
        "`emit_research_findings` once."
    )


# Per-specialist focus tails. Appended AFTER the shared addendum so the
# specialist knows what subset of the catalog they own.
_RESEARCH_FOCUS: dict[str, str] = {
    "cso": (
        "\n\n## YOUR RESEARCH SCOPE (Chief Strategy Officer)\n"
        "Focus on:\n"
        "  - DIRECT COMPETITORS named in `competitive_landscape.primary_competitors` — "
        "their product launches, M&A activity, executive moves, funding "
        "rounds, market positioning shifts.\n"
        "  - Industry analyst reports relevant to the company's category "
        "(Gartner, Forrester, IDC, a16z, Tomasz Tunguz).\n"
        "  - Patent filings / USPTO activity in the company's tech class.\n"
        "Suggested audiences typically: 'principal' for strategic moves, "
        "'department:<owning_dept>' for tactical, 'watchlist' for ongoing "
        "competitor monitoring."
    ),
    "cfo": (
        "\n\n## YOUR RESEARCH SCOPE (Chief Financial Officer)\n"
        "Focus on:\n"
        "  - Stock moves on the company's own ticker (if public) and on "
        "every public competitor.\n"
        "  - Earnings / guidance from competitors and key customers.\n"
        "  - Macro shifts that move the model: rate decisions if "
        "leveraged, FX if multi-currency, sector ETFs the company "
        "tracks with.\n"
        "  - Credit-rating moves on material counterparties.\n"
        "Suggested audiences typically: 'principal' for material moves, "
        "'watchlist' for ongoing ticker tracking."
    ),
    "cmo": (
        "\n\n## YOUR RESEARCH SCOPE (Chief Marketing Officer)\n"
        "Focus on:\n"
        "  - Brand mentions / sentiment spikes (HN, Reddit, X).\n"
        "  - Category-leader content moves, viral threads in the space.\n"
        "  - Search-trend shifts in the company's top keywords.\n"
        "  - Ad-platform anomalies (CPM/CPC spikes that affect budget).\n"
        "Suggested audiences typically: 'department:marketing' for "
        "executable items, 'principal' for narrative-shaping moves."
    ),
    "coo": (
        "\n\n## YOUR RESEARCH SCOPE (Chief Operating Officer)\n"
        "Focus on:\n"
        "  - VENDOR STATUS — incidents on dependencies in the stack "
        "(Stripe, AWS, GitHub, Cloudflare, Twilio …). Use web_search to "
        "confirm the incident is live + impact scope.\n"
        "  - Supply chain / shipping disruptions for physical goods.\n"
        "  - Cloud-cost anomalies, paging-volume signals.\n"
        "Suggested audiences typically: 'principal' for active customer "
        "impact, 'department:engineering' or 'department:operations' for "
        "team-actionable."
    ),
    "chro": (
        "\n\n## YOUR RESEARCH SCOPE (Chief HR Officer)\n"
        "Focus on:\n"
        "  - Layoffs at competitors (talent opportunity) — layoffs.fyi.\n"
        "  - Salary-benchmark drift for the company's role bands.\n"
        "  - Visa / immigration changes for the hiring geos.\n"
        "  - Employer-review (Glassdoor) shifts on tracked employers.\n"
        "Suggested audiences typically: 'department:people' for hiring "
        "ops, 'principal' for comp / culture shifts."
    ),
    "cpo": (
        "\n\n## YOUR RESEARCH SCOPE (Chief Product Officer)\n"
        "Focus on:\n"
        "  - Competitor changelogs / release notes — what shipped.\n"
        "  - App-store rating + review-volume moves.\n"
        "  - Framework / SDK breaking changes the product depends on.\n"
        "  - Security advisories (CVEs) on packages in the SBOM.\n"
        "Suggested audiences typically: 'department:product' or "
        "'department:engineering' for actionable, 'workflow:competitive_teardown' "
        "for a major competitor ship."
    ),
    "gc": (
        "\n\n## YOUR RESEARCH SCOPE (General Counsel)\n"
        "Focus on:\n"
        "  - New regulations in the company's industry + jurisdictions.\n"
        "  - Lawsuits filed (own or peer).\n"
        "  - Data-breach disclosures at peer companies.\n"
        "  - Major contract / DPA template updates.\n"
        "Suggested audiences typically: 'principal' for material legal "
        "exposure, 'department:legal' for routine, NEVER broadcast "
        "(see persona privacy invariant)."
    ),
}


def default_research_focus(specialist_slug: str) -> str:
    """The code-default per-specialist focus tail for a slug (empty if none).

    Exposed so the Agent Council can show the default a custom
    ``research_focus`` override would replace.
    """
    return _RESEARCH_FOCUS.get(specialist_slug, "")


def research_addendum_for(specialist_slug: str) -> str:
    """Return the addendum to append to a specialist's normal system prompt.

    Includes the shared task framing + the per-specialist focus block.
    Unknown specialists get the shared block only; the workflow only
    fans out to slugs in this map, so 'unknown' would be a wiring bug.

    The focus tail is Council-overridable per specialist: a non-null
    ``research_focus`` override on that agent replaces the code default.
    The SHARED contract (``shared_research_addendum``) is never overridable
    — it carries the output schema + grounding/recency/actionability bars,
    so it stays code-only to keep the research output contract intact. The
    override is static config, so it does not break the cached system block.
    """
    from openexecutive.agents.overrides import get_override

    ov = get_override(specialist_slug)
    if ov is not None and ov.research_focus is not None:
        focus = ov.research_focus
    else:
        focus = default_research_focus(specialist_slug)
    return shared_research_addendum() + focus


__all__ = [
    "PER_SPECIALIST_FINDING_CAP",
    "default_research_focus",
    "research_addendum_for",
    "shared_research_addendum",
]
