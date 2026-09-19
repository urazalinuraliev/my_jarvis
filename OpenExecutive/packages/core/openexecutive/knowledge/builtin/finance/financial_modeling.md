# Financial Modeling and Forecasting

A financial model is a tool for decision-making, not a prediction. The number at the bottom right is less important than the assumptions you can defend at the top left.

## The Three Modeling Purposes

Models serve different purposes. Confusing them leads to over-engineering or under-engineering.

**1. Operating model (monthly)**
- Forecasts the next 12-18 months at line-item detail
- Used for: budget setting, monthly variance review, hiring approvals
- Update cadence: monthly

**2. Strategic model (annual)**
- Forecasts 3-5 years at higher level
- Used for: fundraising, board strategy discussions, M&A modeling
- Update cadence: annually plus when material strategy shifts

**3. Decision-specific models (ad-hoc)**
- Single-decision models: hire vs. don't, build vs. buy, expansion economics
- Used for: one specific decision; thrown away or rolled into the operating model afterward
- Built fast, validated against reality, iterated

A 50-tab "everything model" trying to serve all three usually serves none well.

## The Anatomy of a Good Operating Model

**Inputs sheet** (the only place assumptions live)
- Hiring plan by role and quarter
- Revenue assumptions (new bookings, churn, expansion)
- Pricing
- Per-headcount cost assumptions (fully-loaded comp by department)
- Non-payroll opex assumptions (rent, software, marketing, etc.)
- Tax rate, capex, working capital terms

**Calculations sheets** (formulas only, no hard-coded inputs)
- Revenue build (by product, by segment, by motion)
- Cost build (by department, by category)
- Cash flow build
- KPI build (CAC, LTV, NRR, etc.)

**Output sheets** (no formulas, just references)
- P&L summary
- Cash flow summary
- Headcount and comp summary
- KPI dashboard

**Why this structure:**
- Inputs in one place = easy to change scenarios
- Calculations separated from inputs = no broken links when changing assumptions
- Outputs are presentation-ready

**The cardinal rule:** never type a number into a cell that has a formula. Every number traces back to the Inputs sheet.

## Building the Revenue Forecast

**Top-down vs. bottoms-up:**
- *Top-down*: "We'll capture 5% of a $2B market" → useful for sanity check, useless as a plan
- *Bottoms-up*: pipeline × win rate × ACV, or seats × ARPU, or transactions × ARPT → forecastable, defensible

Use bottoms-up for planning; top-down for ceiling check.

**SaaS revenue build:**
```
Starting MRR
  + New MRR (new logos × ACV)
  + Expansion MRR (% of installed base × expansion uplift)
  − Contraction MRR
  − Churned MRR
= Ending MRR
```

Each driver should be modeled separately:
- *New MRR*: pipeline × win rate × ACV (or PLG signups × conversion × price)
- *Expansion*: existing customer cohorts × probability of expansion × expansion size
- *Churn*: cohort retention curves × MRR at risk

**Common mistakes:**
- Plug numbers ("revenue grows 10% per quarter") — no operational lever to pull
- Single ACV assumption across all segments — masks mix shift
- Churn modeled as average — misses cohort variance

## Building the Cost Forecast

**Payroll is 60-80% of opex.** Get it right.

**Headcount-driven cost model:**
- One row per planned hire (role, start date, fully-loaded annual cost)
- Fully-loaded cost = salary × (1 + benefits load) + equity expense
- Benefits load typically 25-35% (depends on geography)
- New hires at 50% productivity in month 1, ramping over 3-6 months for revenue-generating roles

**Non-payroll opex:**
- Variable: scales with revenue or headcount (software, support, infrastructure)
- Fixed: doesn't scale (rent, insurance, audit fees)
- Step function: scales in steps (new office, new region)

Model them separately. Variable costs should auto-scale; fixed costs are explicit assumptions.

## Cash Flow vs. P&L

The two diverge for several reasons that matter for runway planning:

**P&L only:**
- Depreciation and amortization (non-cash)
- Stock-based compensation (non-cash but real dilution)
- Revenue recognized but not yet collected

**Cash flow only:**
- AR / AP timing
- Prepayments received (deferred revenue — cash positive, P&L neutral)
- Capex (P&L sees depreciation; cash sees the full hit upfront)
- Debt principal payments (cash out; not on P&L)
- Tax payments (timing differs from accrual)

For runway calculation, you need cash flow, not P&L. A "profitable" company can run out of cash if working capital is eating it.

## Three Scenarios — The Standard Discipline

Every model should produce three scenarios:

**Base case:** what we believe will happen if execution is on plan
- ~60% confidence we hit or exceed
- The number presented to the board as guidance

**Downside case:** what happens if things break
- Pipeline conversion drops, hires slip, churn spikes
- Typically ~70-80% of base revenue, 100-110% of base costs
- Tests: do we survive? What lever do we pull and when?

**Upside case:** what happens if things go well
- Faster pipeline conversion, big logo lands early, expansion outperforms
- Typically 120-140% of base revenue
- Tests: do we have capacity (people, infrastructure) to support it?

**The decision questions:**
- *Downside*: at what cash threshold do we cut burn? By how much? Which lines?
- *Upside*: at what revenue threshold do we accelerate hiring? Which roles?

Pre-deciding these prevents reactive decisions in either direction.

## Sensitivity Analysis

Which assumptions matter most? Run sensitivity tables on the 3-5 highest-leverage inputs.

**Common high-sensitivity inputs:**
- Revenue growth rate (especially for valuation models)
- Gross margin (for cash flow models)
- Churn rate (for LTV calculations)
- Sales productivity (for hiring decisions)
- Pipeline conversion rate (for forecast accuracy)

Show how the key output (cash runway, ARR, ending cash) changes as each input varies ±20%. The inputs with the steepest output sensitivity are the ones to monitor most closely.

## Reconciling to Reality

A model that never gets compared to actuals is decoration. Every month:

**Variance analysis:**
- Actual vs. budget for each major line
- Investigate variances >5% on revenue, >10% on opex
- Categorize: timing (will normalize) vs. permanent (update the model)
- Update the next-month forecast based on what was learned

**Forecast accuracy:**
- Track actual revenue vs. previous month's forecast over time
- Forecast accuracy of ±5% is excellent
- ±10% is acceptable for early-stage
- >20% means the model isn't being maintained

Models that consistently overshoot reality train the team to discount them. Models that consistently undershoot train the team to ignore them. Calibration is its own discipline.

## Common Modeling Mistakes

1. **Hard-coded numbers in calculation sheets** — breaks the auditability of the model
2. **Single-input assumptions for multi-driver realities** — "10% churn" instead of cohort-based churn curve
3. **No version control** — multiple copies of the model circulating, no single source of truth
4. **Optimistic linear projections** — "if we doubled last quarter, we'll double this quarter forever"
5. **No documentation of assumptions** — six months later, no one remembers why CAC was $X
6. **Ignoring working capital** — high-growth businesses tie up cash in AR; model it explicitly
7. **Conflating ARR with revenue** — ARR is point-in-time; revenue is period — they don't equal each other

## Tools

For most companies <$50M ARR, Google Sheets or Excel suffice. The model's quality depends on the modeler, not the tool.

When to graduate:
- *To dedicated FP&A tools (Pigment, Cube, Mosaic, Anaplan)*: when manual updates take >2 days/month, or when you need scenario modeling across departments
- *To data warehouse + BI*: when data sources are too varied for spreadsheet ingest

Don't graduate prematurely. The tool doesn't fix a bad model.

## The Modeling Diagnostic

For your current operating model, ask:
1. Where are the inputs? Can someone change them and see the effect everywhere?
2. What are the top 3 assumptions that, if wrong, would change the answer most?
3. When did we last reconcile to actuals? What was the variance?
4. What scenario have we NOT modeled that we should?
5. If we had to cut burn 25% next month, would the model tell us where?

If the answer to #5 is "we'd have to rebuild the model to figure that out" — the model isn't a decision tool yet.
