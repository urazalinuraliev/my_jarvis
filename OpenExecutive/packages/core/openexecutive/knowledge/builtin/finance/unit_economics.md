# Unit Economics for Technology Companies

## The Core Equation

**LTV / CAC ≥ 3** is the benchmark for a healthy SaaS business. But understanding why requires knowing what's inside each number.

## Customer Acquisition Cost (CAC)

**Fully-loaded CAC** = (Sales + Marketing Spend) / New Customers Acquired

Include in sales + marketing:
- Salaries and benefits for all sales and marketing headcount
- Advertising spend
- Agency fees
- Events and conferences
- Marketing tools and software
- SDR/BDR time on leads that didn't convert

**Blended vs. segmented CAC**
Blended CAC hides the truth. Separate by:
- Channel (paid search, organic, outbound, partnerships)
- Segment (SMB vs. mid-market vs. enterprise)
- Motion (inbound vs. outbound)

Your best-performing channel at 100 customers will not be your best-performing channel at 1,000. Track the trends.

**CAC Payback Period** = CAC / (ACV × Gross Margin %)

Best-in-class: <12 months for SMB, <18 months for mid-market, <24 months for enterprise.
Benchmark: >36 months payback means you need capital to fund growth.

## Customer Lifetime Value (LTV)

**LTV** = (ARPU × Gross Margin %) / Churn Rate

Or for cohort-based: sum the margin contribution from a customer cohort over their observed or modeled lifetime.

**The inputs that matter most:**
- **Gross margin**: subscription vs. services mix matters enormously. Pure SaaS gross margins should be 70-80%. If you have professional services, run them as a separate P&L.
- **Net Revenue Retention (NRR)**: the single most important metric for a SaaS business. NRR > 100% means your cohorts grow over time. The company can grow even with no new customers.
- **Gross churn**: customers lost. Target <5% annually for SMB, <2% for enterprise. Anything above 10% is a product/market fit problem, not a sales or CS problem.

## Gross Margin Anatomy

SaaS COGS (what lives below the revenue line):
- Cloud infrastructure (AWS/GCP/Azure)
- Customer support headcount
- Third-party API costs embedded in the product
- Amortization of capitalized software development (if applicable)

Do NOT include in COGS:
- R&D / product / engineering building the product
- S&M
- G&A

Rule: if your gross margin is <70% and you're pure software, investigate the COGS line. Either you have a pricing problem (charging too little relative to your cost to serve) or a cost structure problem (infrastructure overbuilt, support understaffed).

## The Startup Phases

**Pre-Product Market Fit**: Unit economics don't matter — survival and learning matter. Optimize for speed of learning, not efficiency.

**Finding PMF**: NRR > 100%, CAC payback trending down, organic referrals growing. These are the signals.

**Post-PMF / Growth**: Now unit economics matter. Before scaling CAC, verify the payback period is within acceptable range and you understand which channels are working.

**Scaling**: Law of large numbers starts working against you. New customer cohorts may be lower quality (you've already acquired the easy customers). Watch for NRR degradation in recent cohorts vs. older ones.

## Quick Diagnostic

If asked "are our unit economics healthy?", check in order:
1. Gross margin ≥ 70%? If not, why not?
2. NRR ≥ 100%? If not, what's driving churn/contraction?
3. CAC payback ≤ 18 months? If not, is it a spend efficiency problem or an ACV problem?
4. LTV/CAC ≥ 3x? This is the summary metric, but fix the inputs above first.
