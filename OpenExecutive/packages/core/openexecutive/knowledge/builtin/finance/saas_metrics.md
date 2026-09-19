# SaaS Metrics — The Complete Stack

The SaaS metric stack diagnoses three questions: (1) is the business growing? (2) is the growth efficient? (3) is the existing book of business healthy?

## Revenue Metrics

**ARR (Annual Recurring Revenue)** — annualized value of subscription contracts in effect today. Excludes one-time fees, professional services, usage overages.
- Use ARR (not GAAP revenue) as the headline metric for subscription businesses. GAAP revenue trails the underlying business.

**MRR (Monthly Recurring Revenue)** — same concept, monthly. ARR / 12 ≈ MRR, but actual MRR is calculated bottoms-up.

**ARR composition** (the "ARR bridge"):
```
Starting ARR
  + New ARR (new logos)
  + Expansion ARR (existing customers buying more)
  - Contraction ARR (existing customers downgrading)
  - Churned ARR (customers leaving)
= Ending ARR
```

If you can't produce this bridge cleanly, you don't really know how your business is growing.

## Retention Metrics

**Gross Revenue Retention (GRR)** = (Starting ARR - Churned ARR - Contraction ARR) / Starting ARR
- Floor only — counts losses, ignores expansion
- Best-in-class: 90%+ SMB, 95%+ mid-market, 98%+ enterprise
- If GRR is below those benchmarks, you have a product/segment fit problem masquerading as a churn problem

**Net Revenue Retention (NRR)** = (Starting ARR - Churned ARR - Contraction ARR + Expansion ARR) / Starting ARR
- Includes expansion — the headline number for SaaS health
- NRR > 100% means cohorts grow over time; the company can grow with zero new customers
- Best-in-class: 110%+ SMB, 120%+ mid-market, 130%+ enterprise
- The single most predictive metric of long-term valuation multiple

**Logo retention** vs. **revenue retention** — different. You can lose 10% of logos but gain revenue if the lost logos were small and remaining accounts expanded. Both matter; revenue is the primary one.

## Efficiency Metrics

**CAC (Customer Acquisition Cost)** = (S&M expense in period) / (new customers acquired in period)
- Fully loaded: salaries, benefits, ads, events, tools, agency
- Segment by channel and customer segment — blended CAC hides the truth

**CAC Payback Period** = CAC / (ARPU × Gross Margin %)
- Months until a customer's contribution margin recovers their acquisition cost
- Best-in-class: <12 months SMB, <18 months mid-market, <24 months enterprise

**Magic Number** = (Net New ARR in quarter × 4) / S&M expense in prior quarter
- Measures S&M efficiency in producing recurring revenue
- >1.0 means S&M is paying back in under a year — aggressive growth justified
- 0.5-1.0 is healthy; <0.5 means slow down spending and investigate

**Burn Multiple** = Net Burn / Net New ARR
- How much cash burned to add a dollar of ARR
- <1.0 = excellent (rare); 1-2 = good; 2-3 = acceptable; >3 = inefficient
- The most honest single-number efficiency metric

**Rule of 40** = Revenue Growth Rate % + EBITDA Margin %
- Should sum to 40+ for a healthy SaaS business
- High-growth at negative margin is OK; mature with high margin is OK; the trade-off is the point
- Useful for valuation conversations with public-market comparables

## Unit Economics Metrics

**LTV (Lifetime Value)** = (ARPU × Gross Margin %) / Annual Churn Rate
- Simple version assumes constant ARPU, constant churn
- Better: cohort-based LTV summing actual margin contribution over observed life

**LTV / CAC** ≥ 3 — long-standing benchmark, but use with caution:
- It rewards low-churn businesses even if growth is slow
- A 5:1 LTV/CAC at 20% growth is worse than a 3:1 at 80% growth for venture-scale businesses
- Combine with payback period — a 5:1 ratio with 36-month payback is a cash problem

**Quick Ratio** = (New MRR + Expansion MRR) / (Contraction MRR + Churned MRR)
- Growth dollars per loss dollar
- >4 is excellent; 2-4 is healthy; <2 is treading water

## Pipeline and Sales Metrics

- **Pipeline Coverage** = Pipeline value / Quota — 3-5x is the working norm; below 3x means missed quota is likely
- **Sales Cycle Length** by segment — important for forecasting, not for benchmarking
- **Win Rate** by source, by segment — improving win rates compound; improving lead volume just adds work
- **Average Contract Value (ACV)** trend — rising ACV usually means moving upmarket
- **Pipeline Velocity** = (# opps × win rate × ACV) / sales cycle days — single number for pipeline health

## Customer Success / Engagement Metrics

- **Net Promoter Score (NPS)** — single ask, "0-10, how likely to recommend?" Promoters (9-10) minus Detractors (0-6). Trend matters more than absolute value.
- **Activation rate** — % of new signups that reach the "aha moment" within the first N days
- **DAU/MAU or WAU/MAU** — stickiness; high engagement correlates with low churn
- **Support ticket volume per customer** — rising = product friction or customer mix shift

## Investor-Grade Reporting

Every SaaS company at Series A+ should report monthly to investors:
- ARR (with bridge)
- NRR and GRR (trailing 12 months)
- CAC payback (by segment)
- Burn multiple
- Magic number
- Pipeline coverage
- Cash position and months of runway

Anything missing from this list signals either lack of measurement maturity or willful obscurity. Investors will assume the latter.

## Common Metric Manipulations to Watch For

- **Annualizing a great month** — quoting "$24M ARR run-rate" based on $2M of December MRR that included $500k of one-time annual prepays
- **Excluding "non-core" churn** — defining away churn from customers who "weren't a fit"
- **Bookings vs. ARR confusion** — bookings include one-time fees, services, multi-year prepayments. ARR is recurring only.
- **NRR computed on a cherry-picked cohort** — must be computed on the full cohort from N months ago, not on "active" customers today
