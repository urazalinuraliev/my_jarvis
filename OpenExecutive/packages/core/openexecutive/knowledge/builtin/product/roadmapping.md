# Roadmapping

A roadmap is a public commitment about the future. It is also one of the most-misused artifacts in product management — too often a marketing document presented as a plan, or a feature list presented as a strategy.

## What a Roadmap Is For

A roadmap serves three audiences with three different needs:

1. **Customers and prospects** — want to know "is this product going to keep solving my problem?" They want directional confidence, not feature dates.
2. **Internal teams** (sales, marketing, success) — want to know "what can I credibly promise customers?" They need enough specificity to position deals.
3. **Engineering and product teams** — want to know "what are we building, and why?" They need the context behind the priorities.

One roadmap can't serve all three audiences well. Most mature product orgs maintain different versions for different audiences.

## Three Roadmap Formats

### Now / Next / Later

Three buckets, no fixed dates.

- **Now** — currently in development
- **Next** — committed for the next cycle
- **Later** — direction but not committed

**Strengths:**
- Honest about uncertainty
- Doesn't lock in dates that will slip
- Customer-friendly without sales-team weaponization

**Weaknesses:**
- Sales hates it ("when will it ship?")
- Doesn't communicate dependencies
- "Later" becomes a dumping ground

Best for: external/customer-facing roadmaps; product-led companies; categories where competition isn't date-driven.

### Theme-Based Roadmap

Themes (strategic areas) at top; outcomes/initiatives within each theme; loosely time-phased.

```
            Q1                Q2                Q3
Theme A:    initiative 1      initiative 2      ---
Theme B:    initiative 3      ---               initiative 4
Theme C:    initiative 5      initiative 6      initiative 7
```

**Strengths:**
- Connects roadmap to strategy (themes reflect strategic priorities)
- Outcomes-oriented (initiatives can ship in multiple forms)
- Resilient to specific feature changes

**Weaknesses:**
- Themes can become too abstract ("improve UX") to be useful
- Internal stakeholders may push for feature-level detail

Best for: internal alignment; cross-functional planning; companies where strategy actually drives the roadmap.

### Feature-Date Roadmap

Specific features, specific quarters or months.

**Strengths:**
- Sales loves it
- Easy to communicate externally
- Forces clarity on what's actually planned

**Weaknesses:**
- Brittle — every change requires a roadmap update
- Encourages over-promising
- Customers treat all dates as commitments

**When to use:**
- Specific contractual commitments
- Critical compliance features
- Internal engineering planning at sprint level

**When NOT to use:**
- External / customer-facing
- Anything more than 1 quarter out
- Anything where the team hasn't confirmed feasibility

Most mature orgs use feature-date roadmaps internally for the current quarter, theme-based for 2-4 quarters out, and Now/Next/Later for external communication.

## Outcomes vs. Outputs

The single most important roadmap discipline.

**Output** — a feature shipped. "Built the new dashboard."

**Outcome** — a measurable change in user or business behavior. "Reduced time-to-first-value from 14 days to 7 days."

Output-based roadmaps measure activity. Outcome-based roadmaps measure value.

**The problem with output-based roadmaps:**
- Teams optimize for shipping, not impact
- Hard to know if the work was worth doing
- Encourages feature-fatigue ("we shipped 47 features and grew 3%")
- Customers feel things changing constantly without clear improvement

**The shift to outcome-based:**
- Each roadmap item is a target outcome (with a metric)
- The "how" (specific features) is the team's call
- Multiple feature attempts may be needed to hit the outcome
- Ship/no-ship decision is based on did-it-move-the-metric, not did-it-launch

**Operational implication:**
- Outcome roadmaps require instrumentation — you must be able to measure the change
- They require permission to NOT ship — if a build doesn't hit the outcome, kill it
- They require longer cycles — outcomes take 6-12 weeks to measure reliably

## Roadmap Communication

### To Customers

**Do:**
- Share themes and direction, not dates
- Use "we're investing in X" language
- Confirm receipt of their specific request without committing
- Tell them when something they care about has actually shipped

**Don't:**
- Commit to dates for unbuilt features
- Show internal/eng-version roadmap externally
- Promise a specific feature in response to a deal — if you must, mark it as a "directional commitment based on this customer's input"

### To Sales

**Do:**
- Give them current quarter feature confidence (high/medium/low)
- Brief them on shifts before they hear elsewhere
- Equip them with FAQ for common feature asks ("not on roadmap because X" vs. "in development for Q3")

**Don't:**
- Let sales sell vapor — burned customers and burned trust
- Update sales last (they often hear from customers first)
- Treat sales requests as discovery (they're a signal, not a verdict)

### To Engineering

**Do:**
- Provide the WHY behind each item, not just WHAT
- Sequence by dependency, not just priority
- Build in slack — 100% utilization is brittle
- Communicate trade-offs explicitly when scope changes

**Don't:**
- Surprise the team with new top-priority items every week (signals you don't have a strategy)
- Add features without removing others (capacity is finite)
- Treat the roadmap as set in stone (it should evolve with learning)

## Roadmap Cadence

**Weekly:** team-level prioritization within the current cycle. Tactical adjustments.

**Monthly:** quarterly roadmap review with leadership. Are we on track? What's slipping? What's a new candidate?

**Quarterly:** full roadmap refresh. Re-evaluate themes, drop completed items, add new priorities.

**Annually:** strategic re-grounding. Are the themes still right? What's changed about the market, customers, competition?

## Roadmap Anti-Patterns

**1. The launch list**
- Roadmap = list of feature launches
- No connection to outcomes or strategy
- Cure: convert each item to an outcome statement

**2. The customer-request log**
- Roadmap = top 10 customer-requested features
- Squeakiest wheels drive the roadmap
- Cure: synthesize requests into themes; prioritize themes, not individual requests

**3. The sales-driven roadmap**
- Every quarter shaped by "we need X to win Y deal"
- Roadmap drifts toward the customer-of-the-week
- Cure: deal-driven features tracked as separate "commercial commitments" with explicit trade-offs

**4. The strategy-free roadmap**
- Items are listed; no connection to strategy
- Hard to defend any specific priority
- Cure: each item carries a "supports strategy by..." tag

**5. The fictional roadmap**
- Roadmap reflects what leadership wants to communicate, not what teams are actually working on
- Communication and reality diverge
- Cure: use the same source-of-truth roadmap internally and externally (suitably summarized)

**6. The dependency-blind roadmap**
- Items planned in isolation; dependencies discovered during build
- Q3 items can't start because Q2 items slipped
- Cure: dependency map visible alongside the roadmap; treat critical-path items as critical-path

## The Hard Conversation

The most common roadmap conversation: "Can we add X?"

The correct answer is rarely "no" or "yes." It is: "What comes out?"

This forces the conversation to be about trade-offs, not additions. Teams without this discipline accumulate roadmaps that exceed their capacity by 2-3x, leading to either heroic over-delivery (burning out the team) or quiet failure (items just don't ship).

## The Roadmap Test

For any roadmap, ask:
1. Does each item have a target outcome and a way to measure it?
2. Is the strategic rationale visible for each item?
3. Can the team explain why these items beat the items NOT on the roadmap?
4. Are dependencies and risks marked?
5. When was the last time we cut something because the data said it wasn't working?

If item 5 has no answer, the roadmap is a wishlist, not a managed plan.
