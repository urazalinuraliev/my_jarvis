# Product Prioritization Frameworks

Prioritization is the central act of product management. The questions are always: of all the things we could build, what do we build first? What do we say no to? How do we explain the choice to people who wanted us to choose differently?

## The Two Failure Modes

**1. The HiPPO (Highest-Paid Person's Opinion) trap**
- Whoever shouts loudest, or pays the most, wins
- Roadmap drifts to executive preference rather than customer value
- Symptoms: roadmap changes after every leadership meeting

**2. The framework-as-decision trap**
- A framework spits out a number; the number "decides"
- No one questions the inputs (which embed all the assumptions)
- Symptoms: spending more time scoring than building

Good prioritization is judgment supported by frameworks, not judgment outsourced to them.

## RICE

Reach × Impact × Confidence / Effort

- **Reach** — how many users/customers affected per quarter
- **Impact** — how much it affects each one (massive 3 / high 2 / medium 1 / low 0.5 / minimal 0.25)
- **Confidence** — how sure are you the numbers are right (high 1.0 / medium 0.8 / low 0.5)
- **Effort** — engineering-weeks (person-weeks)

Score = (Reach × Impact × Confidence) / Effort

**Strengths:**
- Forces explicit assumption about each driver
- Confidence multiplier punishes hand-wavy estimates
- Effort in denominator surfaces high-cost low-value items

**Weaknesses:**
- "Impact" is subjective and hard to compare across categories (new feature vs. infrastructure)
- Doesn't account for sequencing dependencies
- Bias toward easy-to-score items (skip the work where Reach is undefined)

Best for: prioritizing within a defined backlog of comparable items (e.g., growth team's experiment queue).

## ICE

Impact × Confidence × Ease (simpler variant of RICE — no separate Reach)

- Faster to apply than RICE
- Loses the explicit "how many" signal of Reach
- Useful for: rapid prioritization in early-stage, fewer items to score

## MoSCoW

Must-have / Should-have / Could-have / Won't-have

- **Must**: required for the release to function
- **Should**: important but not blocking
- **Could**: nice if time allows
- **Won't**: explicitly out of scope for this cycle

**Strengths:**
- Lightweight, easy to communicate
- Forces "Won't" — explicit deprioritization is the point
- Useful for release planning and scope conversations with stakeholders

**Weaknesses:**
- "Should" becomes a dumping ground
- No relative ranking within categories
- Doesn't surface effort or value tradeoffs

Best for: release scoping, scope negotiation with stakeholders, sprint planning.

## Kano Model

Categorizes features by how they affect customer satisfaction:

- **Threshold (basic)** — expected; absence causes dissatisfaction; presence doesn't delight (login works, app doesn't crash). Must-have.
- **Performance (linear)** — more is better, linearly (faster load, more storage, lower price)
- **Excitement (delighter)** — unexpected; absence doesn't dissatisfy; presence delights (and creates a new threshold for next time)
- **Indifferent** — customers don't care
- **Reverse** — more of it actually hurts satisfaction (bloat, complexity)

**How to use:**
- Survey customers: "How do you feel if the product has X? How do you feel if it doesn't have X?"
- Classify each feature based on the response combination
- Invest in: shoring up Thresholds first, then strategic Performance bets, then targeted Excitement features
- Cut: Indifferent and Reverse

**Strengths:**
- Surfaces hidden assumptions (we're spending on Indifferent features)
- Explains why "more features" sometimes hurts satisfaction
- Anchors prioritization in customer perception, not internal opinion

**Weaknesses:**
- Categories shift over time (today's delighter is tomorrow's threshold)
- Requires real customer research, not just internal classification

Best for: roadmap themes, investment area decisions, strategic feature mix.

## Weighted Shortest Job First (WSJF)

(Cost of Delay) / Job Size

Cost of Delay = User-Business Value + Time Criticality + Risk Reduction / Opportunity Enablement

**Strengths:**
- Explicitly models time-sensitivity (a feature with a competitive window has high time criticality)
- Captures non-revenue value (risk reduction, optionality)
- Used widely in SAFe / large enterprise contexts

**Weaknesses:**
- More inputs = more places for bad numbers to slip in
- Numerical precision can mask qualitative judgment
- Best for organized backlogs, not exploratory work

Best for: SAFe-style scaled agile teams, programs with many cross-cutting initiatives.

## Opportunity Scoring (Outcome-Driven Innovation)

For each customer outcome:
- **Importance** (how important to the customer): 1-10
- **Satisfaction** (how well current solutions address it): 1-10
- **Opportunity** = Importance + max(Importance - Satisfaction, 0)

Higher opportunity score = bigger gap to fill.

**Strengths:**
- Directly customer-anchored
- Surfaces underserved jobs even when no one is asking about them
- Pairs naturally with JTBD interviewing

**Weaknesses:**
- Requires structured customer research to populate
- "Outcome" definition matters enormously — vague outcomes produce useless scores
- Slow to update; not for high-velocity decisions

Best for: strategic roadmap planning, new market entry, major investment decisions.

## Cost of Delay (CoD)

If we don't ship this feature for another quarter, what does it cost us?

- Lost revenue (deals lost to competitors)
- Increased churn risk (existing customers leaving)
- Customer acquisition cost (each month delayed = more spend to acquire)
- Strategic positioning (window closing)
- Opportunity cost (other features we could be building)

**Strengths:**
- Forces conversation about time as a cost, not just resources
- Highly effective for cross-functional prioritization conversations (sales pushing for X)
- Doesn't require a single composite score

**Weaknesses:**
- Easy to inflate numbers ("we'll lose $10M if we don't ship this")
- Sales-driven items always look like high CoD; need to triangulate with customer data

Best for: cross-functional prioritization debates, escalations to leadership.

## The Eisenhower Matrix (for time-bound prioritization)

|  | Urgent | Not Urgent |
|---|---|---|
| **Important** | Do now | Plan |
| **Not Important** | Delegate | Drop |

Less commonly used for product backlog (more for personal task management), but useful for the daily "what should I work on?" question.

## A Simpler Question Set (Sometimes the Best Framework)

When a framework is overkill, ask:

1. What problem does this solve? Whose problem?
2. How many customers have this problem? How acutely?
3. What happens if we don't solve it?
4. What does our solution look like? How long to build?
5. What does success look like? How will we know?

If a feature can't survive these five questions, it shouldn't be on the roadmap regardless of what any framework says.

## Combining Frameworks

Most mature product orgs use 2-3 frameworks at different altitudes:

- **Strategic** (annual): Opportunity scoring, Kano, JTBD — what general areas to invest in
- **Tactical** (quarterly): RICE, WSJF — what specific items to prioritize within an area
- **Operational** (sprint): MoSCoW — what's in or out of this release

Trying to use one framework for all three is how prioritization becomes either too generic or too granular.

## Stakeholder Communication

Whatever framework you use, the communication discipline:

**Show the math.** When you say no, show what you said yes to instead and why it ranked higher.

**Be specific about disagreement.** "I disagree with X's Impact score of 3 — I think it's 1 because..." is more productive than "the framework is broken."

**Reserve override authority.** Frameworks inform; PM (or product leader) decides. Trying to make the framework the decider is how you get gamed inputs.

**Document the calls.** Six months later, when sales asks "why didn't we build feature X?", you want to be able to show the explicit reasoning, not reconstruct it.

## The Prioritization Test

For any roadmap, ask:
1. Can a customer-facing person explain why each item is on the list?
2. Can you point to the item you're MOST excited to ship and explain why it's #1?
3. What's the most painful "no" on the list — what we explicitly chose not to do?
4. Who's the customer that gets value from the top 3 items? Are they the customer we're trying to win?
5. If the team had 50% less capacity, what would we cut?

If you can answer all five, you have prioritization. If you can't, you have a wishlist.
