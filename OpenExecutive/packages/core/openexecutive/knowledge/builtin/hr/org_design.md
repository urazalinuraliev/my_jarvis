# Organizational Design

Structure shapes behavior. The org chart determines who talks to whom, who owns what, and which problems get solved. Most "strategy execution" problems are actually org design problems.

## Conway's Law (the most underappreciated principle in org design)

"Organizations design systems that mirror their own communication structure."

The product you ship will look like the org chart that built it. If you want a coherent product, you need a coherent org. If two teams own halves of a customer experience, the seam between them will be visible in the product.

**Operational implications:**
- Define team boundaries to match the product or customer outcome you want, not legacy functional silos
- When you change strategy, change structure — don't expect the same team to ship a different product
- Avoid "matrix everywhere" — dotted lines create plausible deniability for outcomes

## Spans and Layers

**Span of control** — number of direct reports a manager has. Healthy ranges:
- Senior IC managers: 5-8 reports
- People managers: 7-10 reports
- Frontline (high task similarity): 10-15 reports
- Executives: 6-9 direct reports — beyond that, they become a switchboard, not a leader

**Layers** — depth from CEO to frontline IC. Each additional layer adds latency, distortion, and cost.

Heuristic:
- <50 people: 3 layers (CEO → manager → IC)
- 50-200: 4 layers (CEO → executive → manager → IC)
- 200-1000: 5 layers
- >1000: 6 layers

Layer growth should lag headcount growth. Most companies over-layer in response to politics (creating new VP slots to retain people) rather than need.

## Organizational Archetypes

**Functional** (engineering, sales, marketing, finance each as their own org)
- *Strengths*: deep expertise within each function, clear career paths, efficient resource pooling
- *Weaknesses*: slow cross-functional coordination, every product decision requires multi-function alignment
- *Best for*: single-product companies; back-office and infrastructure roles

**Product / Business Unit** (each product or BU owns its own functions)
- *Strengths*: full P&L ownership, fast decisions within unit, customer focus
- *Weaknesses*: duplicated capability across units, harder to share talent or best practices
- *Best for*: multi-product companies, geographic expansions, mature platforms

**Matrix** (employees report to both function and product/BU)
- *Strengths*: leverages functional depth + product focus
- *Weaknesses*: dual reporting confusion, accountability dilution, politics
- *Best for*: large companies that need both — but only with explicit rules about which reporting line decides what

**Tribes/Squads (Spotify model)**
- Cross-functional squads aligned to a mission; chapters for functional discipline; tribes for related squads
- *Reality check*: Spotify itself acknowledged they didn't fully implement this — it's an aspiration, not a recipe. Borrow ideas, don't copy the model.

**Pod / Triad** (engineering + product + design tightly coupled)
- *Strengths*: tight feedback loops, customer focus, autonomy
- *Weaknesses*: harder to do platform/infrastructure work; coordination across pods can fail
- *Best for*: product-led companies post-PMF

## Decision Rights — Who Decides What

Structure tells you who reports to whom. Decision rights tell you who actually decides. The two should align but often don't.

**RACI framework:**
- **R**esponsible — who does the work
- **A**ccountable — who owns the outcome (only one)
- **C**onsulted — input before decision
- **I**nformed — told after decision

If RACI has multiple A's, you have no accountability. If RACI has no consulted but the outcome touches other functions, you have a coordination failure waiting to happen.

**DACI** — alternative with Driver (manages process), Approver (decides), Contributors (provide input), Informed (notified). Forces explicit separation of "drives the meeting" from "calls the decision."

**RAPID** — Recommend, Agree, Perform, Input, Decide. Bain's variant. Useful for decisions involving an explicit approval chain.

Pick one. The framework matters less than using it consistently.

## Team Boundaries — Where to Draw Them

Three viable principles:
1. **By customer** (account team, customer segment) — best for relationship-driven businesses
2. **By product** (mobile team, payments team) — best for engineering organizations
3. **By workflow / process** (intake, fulfillment, support) — best for operational businesses

Hybrid is fine. Avoid is splitting a single customer experience across multiple owners.

**Two-Pizza Rule** (Bezos): a team should be small enough that two pizzas can feed them. 6-10 people. Below 5, you don't have enough functional coverage. Above 10, coordination overhead dominates.

**Inverse Conway Maneuver**: design the team structure you want, then the architecture will follow. Used when reshaping an existing system: change the org first, the system will reshape itself.

## Common Org Design Anti-Patterns

1. **Matrix everywhere without clear rules** — dual reporting with no decision-rights framework. Outcome: politics determines who wins each fight, not strategy.

2. **Title inflation as retention tool** — promoting someone to VP because they threatened to leave. Outcome: org bloat, level corruption, real VPs lose trust in the title.

3. **Reorgs to avoid hard people decisions** — restructuring to move someone out of a role rather than confront performance. Outcome: structural damage to retain one person; the structure communicates the avoidance.

4. **Functional silos disguised as autonomy** — "you own your function" used to justify zero cross-function collaboration. Outcome: each function optimizes locally, the customer experience falls apart.

5. **Snowflake teams** — every team has a unique reporting structure because of some special situation. Outcome: managers can't predict how decisions get made; new hires can't orient.

## Reorg Discipline

Reorgs are expensive. Each one consumes 3-6 months of productivity in the affected teams. Rules:

- Don't reorg more than every 18 months for a given team without a strategic forcing function
- Define the problem you're solving (not "things feel off") and the success metric for the new structure
- Announce reorgs all-at-once with the full picture, not progressively (each announcement triggers another wave of uncertainty)
- New structures take 90 days to stabilize. Don't judge the result before then.

## Diagnostic Questions

When something isn't working, before assuming it's a people problem, ask:

1. Who owns this outcome? (If you can't name one person, that's the problem)
2. Do they have the authority to deliver it? (Authority = budget + headcount + decision rights)
3. Are they the right level for the scope? (Don't ask a director to do VP work; don't ask a VP to do director work)
4. Who must they coordinate with, and is that coordination working?
5. Does the structure encourage or punish the behavior we want?

Most "performance" problems answer "no" to one of these — and no amount of coaching the individual fixes a structural mismatch.
