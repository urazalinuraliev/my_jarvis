# Product-Market Fit

Product-market fit (PMF) is the most important concept in early-stage company building and also the most-abused. Most claims of PMF are wrong; most companies that have it don't have to claim it. Recognizing PMF — and recognizing its absence — is the difference between scaling a working business and burning capital on a broken one.

## What PMF Actually Is

The original definition (Andreessen): "You can always feel when product/market fit isn't happening. The customers aren't quite getting value out of the product, word of mouth isn't spreading... And you can always feel product/market fit when it's happening. The customers are buying the product just as fast as you can make it."

The operating definition: customers love the product enough that the business pulls itself forward. Acquisition gets easier, not harder. Retention is strong without heroic CS effort. Customers refer others without being asked.

**The honest test:** if you stopped doing outbound and PR for 3 months, would the business stop growing? If yes, you don't have PMF — you have demand generation.

## PMF Signals (Operational)

No single metric defines PMF. The signals come together as a pattern:

**Quantitative signals:**

- **Retention curve flattens** at a meaningful percentage (not declining to zero) — see `product_analytics.md`
- **NPS > 30-50** for the product (with promoter rate matching)
- **Net Revenue Retention > 100%** (for SaaS)
- **Organic growth contribution > 30-40%** (customers coming from referral, search, word of mouth)
- **CAC payback declining** as the product matures
- **40%+ "very disappointed"** on the Sean Ellis test (see below)
- **Power user curve** with a meaningful concentration

**Qualitative signals:**

- Customers describe the product in their own words consistently (the value proposition is "obvious" to them)
- Customers proactively expand usage without prompting
- Customers refer colleagues unsolicited
- Customers complain when you don't ship the next feature (they're invested)
- Sales team has to fend off inbound, not generate outbound
- Customer support becomes about advanced features, not basic confusion

The pattern matters more than any single signal. A few weak signals is not PMF. A pile of strong signals from independent measures usually is.

## The Sean Ellis Test

The most-cited PMF test. Ask current users:

> "How would you feel if you could no longer use [product]?"
> 
> Options: Very disappointed / Somewhat disappointed / Not disappointed / N/A (no longer using)

**The 40% rule:** if 40%+ of respondents say "very disappointed," you have PMF.

**Caveats:**
- Only ask active users (not signups who never adopted)
- Single product question; doesn't capture full business picture
- Threshold is heuristic, not law
- Some products achieve PMF at 30%; some require 50%

**Follow-up questions:**
- "What would you use instead?" — reveals competitive set
- "What type of person do you think would most benefit?" — reveals real ICP
- "What's the main benefit you receive?" — reveals real value prop
- "How would you improve [product]?" — reveals product gaps

These follow-ups are often more valuable than the 40% number itself. They tell you what's working and where to go next.

## The Retention Curve

The single most diagnostic signal of PMF.

**Plot:**
- X-axis: time since signup (day, week, month)
- Y-axis: % of cohort still active
- Plot per cohort (week 1 signups, week 2 signups, etc.)

**Three patterns (see also `product_analytics.md`):**

1. **Decay curve** — continuous decline; asymptotic to zero. No PMF.
2. **Smiling curve** — drops then stabilizes (sometimes rises). PMF with the segment that stays.
3. **Drop and flat** — significant drop then horizontal. Partial PMF; investigate who stays vs. who churns.

**The honest read:**
- If the curve isn't flattening, you don't have PMF for this segment / use case
- The level it flattens at indicates the size of the PMF audience
- Improving the curve is the work; flat decay isn't fixed by acquisition

**Per-segment retention:**
- Cohort by industry, company size, use case, persona
- Often: PMF in one segment, not in others
- Strategy: focus on the segment where PMF exists; learn before expanding

## The "Pull" Test

Beyond metrics: does the market pull, or do you push?

**Pulled-by-market signs:**
- Inbound leads from search and referral exceed outbound results
- Sales cycle compresses over time
- Customers do the selling internally (champion-led, multi-stakeholder)
- You can charge more without losing the deal
- Customer success is mostly account expansion, not retention firefighting

**Push-still-required signs:**
- Heavy outbound to maintain pipeline
- Long sales cycles requiring extensive education
- "I just need to convince [other stakeholder]" before close
- Pricing pressure on every deal
- High-touch customer success required to retain

A business can be working without PMF — but the unit economics are usually broken, and the business stops growing when you stop pushing.

## Finding PMF — The Iteration Loop

PMF rarely happens on the first version. It happens through fast iteration on:
- The customer (segment, persona, ICP)
- The problem (which job-to-be-done you're solving)
- The solution (the product itself)

**The discovery loop:**
1. Hypothesize the customer + problem + solution
2. Build the smallest thing that tests the hypothesis
3. Get it in front of target customers (10-50, not 1000)
4. Measure quantitatively (retention, conversion) AND qualitatively (interviews)
5. Update the hypothesis
6. Repeat

**Common iteration patterns:**
- *Same customer, different problem*: customer is right, you're solving the wrong thing for them
- *Same problem, different customer*: the problem is real but the wrong segment
- *Same customer + problem, different solution*: right diagnosis, wrong product
- *Restart entirely*: pivot to a new customer + problem

**The honest signals to pivot:**
- Multiple cohorts churning
- "Nice to have" feedback consistently (not "I need this")
- Sales requires founder presence to close
- Customers can't articulate the value when you ask them
- Acquisition costs rising despite product improvements

The longer you operate with these signals, the more capital and time burned for nothing.

## False PMF — The Trap

The most dangerous condition: appearing to have PMF when you don't.

**False PMF patterns:**

1. **Heavy outbound masking organic shortfall**
- 200 leads/month from outbound; "growing 10% monthly"
- Stop outbound; growth disappears
- Mistaken for PMF because the top-line is up

2. **Concierge service masquerading as product**
- "Customers love it!" because the founder personally onboards every account
- Won't scale — but feels like PMF until you try to remove the human

3. **Heavy discounting**
- Customers buy at 50% off list — they value the price, not the product
- Real value prop is unclear because the discount distorts the signal

4. **Single-customer concentration**
- One big customer drives growth; their happiness is the metric
- Their departure destroys the business
- Not PMF — it's a project for one client

5. **PR / brand momentum**
- Press coverage drives signups; signups don't convert; conversion don't retain
- Top-of-funnel without the rest

**The diagnostic for false PMF:** what would your numbers look like with no marketing spend, no founder-led sales, no manual concierge service? That's your true PMF baseline.

## The Path After PMF

PMF doesn't last forever. The world changes; markets mature; competitors emerge. Maintaining PMF is its own ongoing discipline.

**Post-PMF priorities:**
- Scale the engine (sales, marketing, customer success) that converts PMF into revenue
- Defend the segment (don't lose existing customers to better-positioned competitors)
- Expand the product (deepen value with the segment that has PMF)
- Cautiously test adjacencies (new segments, new use cases — but with PMF rigor)

**The PMF-to-scale failure mode:**
- Company achieves PMF
- Doubles down on aggressive growth
- Quality / culture / customer experience suffer
- Existing PMF erodes faster than new customers compensate
- Growth stalls; company struggles to recover

## Re-Finding PMF

If you've lost PMF — or never really had it — the path back is the path to:
1. Stop trying to scale (acquisition spending masks the underlying problem)
2. Reconnect with customers (deep interviews, JTBD work, retention root-cause analysis)
3. Reduce the surface area (focus on the use case and segment that worked best)
4. Iterate on product and positioning together
5. Test the Sean Ellis question quarterly; measure retention curves cohort-by-cohort

This is uncomfortable. Many companies refuse to admit they've lost PMF (or never had it) and keep scaling. The capital burn before they reckon with reality is often 12-24 months.

## The PMF Diagnostic

Ask:
1. What's our cohort retention curve at 6 months? Is it flat or declining?
2. What % "very disappointed" on the Sean Ellis test, by segment?
3. What % of new growth came from organic (referral, search) vs. paid + outbound?
4. If we stopped acquisition spending for 3 months, what would happen?
5. Can our customers describe what we do, in their own words, consistently?

If any answers are uncomfortable, that's the answer. PMF doesn't reveal itself through wishful thinking.
