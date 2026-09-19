# Pricing and Packaging

Pricing is the highest-leverage decision in the business. A 1% price increase, holding volume constant, is roughly equivalent to a 10% cost reduction in profit impact. Most companies leave 10-30% on the table because they price by feel.

## Three Pricing Philosophies

**1. Cost-plus** — calculate cost, add a margin
- Right for: commodity businesses, regulated industries, capital-intensive services
- Wrong for: software, anywhere with variable willingness-to-pay
- Why it loses for software: marginal cost is near zero, so cost-plus undervalues the product

**2. Competitor-based** — benchmark to alternatives, position relative
- Right for: established categories with clear comparables
- Wrong for: differentiated products, new categories
- Why it loses long-term: chains your pricing to competitors who may be pricing wrong

**3. Value-based** — price as a function of the value delivered to the customer
- Right for: differentiated software, transformational products
- Wrong for: nothing, but it requires knowing what the customer values, which is hard
- The default for SaaS done well

## Value-Based Pricing — The Mechanics

To price based on value, you need to quantify what the customer gets.

**Value quantification:**
- Hard ROI: cost savings, revenue lift, time savings × cost of time
- Soft value: risk reduction, strategic optionality, organizational capability
- Substitute cost: what would it cost to do this another way (build internally, hire consultant, use point solutions)

**The pricing range:**
- *Floor*: your variable cost (don't sell below this unless deliberately)
- *Ceiling*: customer's willingness-to-pay (driven by value perceived)
- Your strike price is somewhere in this range — leaning toward the value-end when you have leverage (differentiation, urgency, no alternative), toward the cost-end when you don't

**Capture ratio:**
- Most companies capture 10-30% of the value they create
- Higher capture is possible but requires customers to clearly see and credit you for the value
- If you're capturing >50%, expect customer churn or pricing pressure

## Pricing Models for SaaS

**Per Seat / Per User**
- Value scales with adoption — natural alignment
- Easy to forecast for both buyer and seller
- Risk: discourages broader rollout (each new seat costs money); cap at some breakpoint or include unlimited tiers

**Usage-Based / Consumption**
- Customer pays for what they use (API calls, GB processed, transactions)
- Aligns cost with value delivered
- Risks: revenue unpredictability for vendor; surprise bills for customer (a category leader, Snowflake, lost goodwill over this)
- Best with prepaid commitment + overage to dampen volatility

**Per Workflow / Per Job**
- Customer pays per output (resume screened, transaction processed, report generated)
- Strong value alignment
- Newer model; works for AI-native products where outputs are countable

**Flat Fee / Site License**
- Simple to buy, simple to sell
- Easy to underprice (no built-in expansion)
- Right for: enterprise platform deals with internal allocation

**Tiered / Good-Better-Best**
- 3-tier structure: entry, standard, premium
- Anchors customer to the middle tier
- Enables clear upgrade path
- Most common SaaS structure for self-service and SMB

**Hybrid models** combine the above (per-seat base + usage overage; tiered subscription + per-workflow add-ons). Common at scale; complex to model.

## Packaging — The Other Half of Pricing

Packaging is which features go in which tier. Done well, it makes the buying decision easy and creates a natural expansion path.

**The framework — pick three dimensions:**
1. **Quantity** (number of seats, queries, projects)
2. **Capability** (which features are in which tier)
3. **Service** (support level, account management, SLA)

**Two principles:**
- *Differentiate enough that customers self-select up*. Each tier should have a clear reason to want the next one.
- *Don't punish your best customers*. Power users hitting limits should naturally upgrade, not feel nickel-and-dimed.

**Common packaging traps:**
- Too many tiers (>4) — paralysis, lost deals
- Free tier too generous — undermines paid conversion
- Free tier too stingy — kills trial-to-paid funnel
- Feature gates that block real value — customers walk away before they see why to upgrade
- Hidden charges (overages, premium support) — corrodes trust

## Free Trials, Freemium, and Free-Forever

**Free trial** (14-30 days)
- Customer gets full product, expires
- Conversion benchmark: 15-25% for self-serve SaaS
- Works when: product value clear in 14 days, low onboarding burden
- Watch: trial extension requests are a quality signal (high value) or a stalling signal (no urgency)

**Freemium** (free tier, paid upgrade)
- Free indefinitely with limits; paid for more capacity or features
- Conversion benchmark: 2-5% of free users to paid in a year
- Works when: free tier has standalone value, paid tier has 10x+ value
- Watch: support cost of free users; calculate paid conversion economics carefully

**Free-forever (community/open source)**
- Full product free; revenue from services, hosting, enterprise tier
- Works when: developer community is the buyer (GitLab, MongoDB)
- Long payback; high investment to maintain

## Price Discrimination

Selling the same thing at different prices to different customers — done legally and ethically through:

- **Segment-based**: SMB vs. enterprise pricing, with different features and prices
- **Geo-based**: lower prices in markets with lower willingness-to-pay
- **Education / Non-profit discounts**
- **Volume discounts** at defined breakpoints
- **Multi-year discounts** in exchange for longer commitment

**Avoid:**
- Negotiated one-off discounts without policy — creates random pricing across the customer base
- MFN clauses — locks you into the lowest price you've ever given
- Public list price that's just an opening anchor — corrodes trust when customers compare notes

## Pricing Changes — The Hardest Operational Move

**Reasons to change pricing:**
- Product has matured and is delivering more value than the price reflects
- Costs have changed materially
- Market position has changed (more differentiated; more commoditized)
- Existing pricing structure is creating bad customer behavior (free tier abuse, sandbagged consumption)

**The big decisions:**
- *Grandfathering existing customers* — usually yes for at least 12 months. Goodwill matters; the cost of churn from a price increase is real.
- *Rolling vs. announce-all-at-once* — announce, give notice (60-90 days), execute. Quiet rollouts get discovered and breed mistrust.
- *Price increase ceiling* — 5-10% annual is sustainable for strong products. >20% requires a story (new capability, restructuring, market correction).

**Communication template for price increases:**
1. What's changing
2. When it takes effect (give time)
3. Why (new value delivered, market dynamics — be honest)
4. What's not changing (the things customers care about staying stable)
5. Offer (lock in current pricing for multi-year commitment, etc.)

## Pricing Research Methods

**Quantitative:**
- *Van Westendorp Price Sensitivity Meter*: ask customers four questions about price points (too cheap, cheap, expensive, too expensive). Identifies acceptable range.
- *Conjoint analysis*: present feature/price bundles; statistical analysis reveals which features drive willingness-to-pay
- *A/B testing*: live pricing experiments on the website (use sparingly; can damage trust if customers compare)

**Qualitative:**
- Win/loss interviews: did pricing kill the deal? At what level?
- Buyer interviews: walk through their evaluation, where did they get tripped up
- Competitive pricing research: secret-shopper, salesperson conversations, public information

**The cheapest experiment:** raise prices 10% on new customers next month. If volume holds, you were underpriced.

## Pricing Operations

**Quote-to-cash:**
- Approval matrix for discounts (rep can give X%, manager X+Y%, VP X+Y+Z%, exec only above)
- Standard ramp deals (Year 1: $50k, Year 2: $75k, Year 3: $100k) — predictable, customer-friendly
- Quarterly pricing review with sales leadership — catch the patterns (we're giving 25% discount on every Q4 deal — why?)

**Renewals:**
- Standard auto-renewal with annual price escalator (CPI + 3% is common)
- Customer comms 90 days before renewal — soft re-engagement plus renewal terms
- Don't quietly raise prices at renewal without telling them — the surprise drives churn

## A Final Diagnostic

For each customer cohort, ask:
1. Are they getting more value over time? (If yes, you have pricing power; use it.)
2. Are renewals at or above original ACV?
3. What % of customers are in the lowest-tier?
4. When did we last raise prices?
5. What's the gap between our list price and our average realized price?

Most pricing problems show up in #5 — a large gap signals undisciplined discounting and is the easiest place to recover revenue.
