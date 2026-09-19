# Valuation Methods

Every valuation is a story about the future expressed in a number. The number you defend depends on which story you believe.

## Discounted Cash Flow (DCF)

The theoretically correct method for valuing any cash-generating asset. Practically constrained by forecast accuracy.

**Mechanics:**
1. Project Free Cash Flow (FCF) for an explicit period (typically 5-10 years)
2. Estimate a terminal value (the value of all cash flows beyond the explicit period)
3. Discount everything back to present value using a discount rate (WACC for the firm, cost of equity for equity-only)

```
Enterprise Value = Σ FCF_t / (1+r)^t  +  Terminal Value / (1+r)^n
```

**Terminal value** typically uses one of:
- *Gordon Growth*: TV = FCF_n × (1+g) / (r-g), where g is perpetual growth rate (usually 2-3%, tied to GDP)
- *Exit multiple*: TV = EBITDA_n × industry multiple

**The WACC inputs:**
- Cost of equity via CAPM: Rf + β × (Rm - Rf)
- Cost of debt: pre-tax cost × (1 - tax rate)
- Weighted by target capital structure

**DCF traps:**
- Garbage in, garbage out — sensitive to growth rate and discount rate; a 1% swing in either materially changes the answer
- Terminal value is often 60-80% of the valuation. Your view on year 10 dominates the answer.
- Useful for *understanding* drivers of value; less useful as the single answer

Always do sensitivity analysis: vary growth and discount rate by ±2% each and show the range.

## Comparable Company Analysis ("Comps" or "Trading Comps")

Apply trading multiples of publicly-listed peers to the target's metrics.

**Common multiples:**
- *EV / Revenue* — used for high-growth or unprofitable companies
- *EV / EBITDA* — used for profitable companies; controls for capital structure and tax
- *EV / Forward Revenue* — for growth companies; multiples are higher because they capture expected growth
- *P/E* — equity-level multiple; only useful for profitable companies

**Process:**
1. Build a peer set (5-15 companies) — same industry, similar size, similar growth profile
2. Pull trading multiples from current prices
3. Apply median (sometimes mean) to target's metrics
4. Adjust for size, growth, margin differences

**Issues:**
- Peer set selection is everything — anyone can defend any valuation by choosing the right comps
- "Multiples" change rapidly with market sentiment; today's median is not next quarter's
- Public market multiples don't transfer cleanly to private companies — apply a illiquidity discount (typically 20-30%)

## Precedent Transactions Analysis

Same as comps, but using multiples from recent M&A deals instead of public trading prices.

**Includes a control premium** — buyers pay 20-40% over standalone market value for control. So precedent multiples > trading multiples for the same company.

**When to use:**
- Selling a company
- Buying a company
- Defending a valuation in a board negotiation

**When to avoid as the primary method:**
- Limited data — comparable transactions are rare and disclosure is incomplete
- Each deal has unique synergies and strategic rationale that don't generalize

## Venture-Stage Methods

DCF and comps both struggle for early-stage companies because cash flows are negative and forecasts are unreliable.

**Venture Method (work backwards from exit):**
1. Estimate exit value at maturity (typically 5-7 years out) — e.g., $1B exit at $100M revenue × 10x multiple
2. Apply target IRR (40-60% for early-stage VC) to discount back
3. Required ownership at exit = investment × (1 + IRR)^years / exit value
4. Adjust for dilution from subsequent rounds — your ownership at exit = today's % × (1 - dilution)

This method tells you what % you need to own today to make the return math work, given the exit you believe in.

**Comparable financing transactions:**
- Recent funding rounds in similar companies at similar stages
- More relevant than public comps for early-stage
- Carta, PitchBook, and Crunchbase aggregate this data

**Revenue / ARR multiples for high-growth SaaS:**
- Pre-revenue: priced on team, market, and progress against milestones
- Seed: $5-15M post-money for credible teams in hot markets
- Series A (>$1M ARR): typically 30-60x ARR for top decile, 15-30x for median
- Series B (>$10M ARR): typically 15-30x forward ARR
- Series C+: trends toward 8-15x forward ARR as growth rates compress

These ranges move with macro conditions. 2021 was 2-3x these multiples; 2023-2024 was at the low end.

## Strategic vs. Financial Value

The same company can have very different values to different buyers:

- **Standalone value** — DCF of the business as-is
- **Strategic value** — standalone + buyer-specific synergies (cost takeout, revenue acceleration, IP)
- **Defensive value** — what a competitor would pay to keep it out of a rival's hands

Sellers should run multiple processes to surface strategic premiums. Buyers should be disciplined: don't pay strategic value unless the synergies are real and you have a credible plan to capture them.

## Sanity Checks Before Defending a Valuation

1. **Per-customer value**: at this valuation, what is each customer worth? Does that pass a smell test against LTV?
2. **Per-headcount value**: at this valuation, what is each employee worth? Compare to comparable companies at the same stage.
3. **Market share at exit**: at the projected exit revenue, what share of the addressable market would the company hold? If >20%, the projection requires market dominance — usually unrealistic.
4. **Payback for new investor**: at this valuation, what return does the new investor need at exit to clear their fund hurdle? Is the implied exit realistic?

If any of these fails, the valuation is a story, not a number.
