# Startup Lifecycle — From Idea to Scale

Most strategy frameworks assume an established company. Startups face a different challenge: surviving long enough to become one. The playbook changes dramatically across stages, and the most common executive failure is running the wrong playbook for the company's actual stage.

## Stage 0: Idea and Validation (Pre-Seed / Bootstrapped)

**The only question that matters:** Does this problem exist, and will people pay to solve it?

**What founders should be doing:**
- Talking to customers — not building. Minimum 50 structured discovery conversations before writing serious code.
- Looking for disconfirmation: the conversations that disprove your thesis are more valuable than the ones that confirm it.
- Finding the early adopters — the subset of the market who has the problem acutely enough to try an imperfect solution.

**What to avoid:**
- Stealth mode — builds things in isolation, discovers the problem doesn't exist after 12 months
- Survey-based validation — people lie in surveys; watching behavior and payment is truth
- Building for the feature list — solutions exist before the problem is understood

**Signals that you're ready to proceed:**
- At least 3-5 customers who would be "very disappointed" if the product disappeared
- Someone has paid real money, or committed to paying when the product ships
- You can articulate the customer segment, the specific problem, and why existing solutions are inadequate

**Common traps:**
- Friends and family as customers (they validate the founder, not the business)
- Conflating interest with intent — "I'd love this" ≠ "I'll pay for this"
- Raising too much pre-validation — money insulates you from customer feedback

## Stage 1: Pre-Seed / Seed — Finding Product-Market Fit

**Funding stage:** $500K–$3M typically. Sometimes bootstrapped.
**Team size:** 2–10 people.
**Primary job:** Find product-market fit (PMF).

PMF is when you've found a product that a defined market segment wants badly enough to grow through word of mouth. Signs:
- Retention curves flatten (users stay)
- Net Promoter Score of 40+ (industry-varying)
- Organic growth — users coming without you pushing them
- Customers complaining when it's down or slow, not just when features are missing

**How to operate at this stage:**
- *Narrow the ICP relentlessly* — "SMB SaaS companies" is not an ICP; "20-100 person SaaS companies that sell to mid-market and have a VP of Sales" is
- *Do things that don't scale* — manual onboarding, personal sales, custom implementations; learn what the product needs to do before automating it
- *Measure retention above everything* — acquisition is meaningless if users churn; cohort retention by week/month is the PMF diagnostic
- *Stay close to customers* — founders doing support and sales; not delegating yet

**What the team should look like:**
- Generalists who can do multiple jobs
- High ownership, low process
- Hire for curiosity and velocity, not credentials

**Capital discipline:**
- Default alive: can the business survive on current revenue growth without another raise?
- Burn multiple: cash burned per dollar of net new ARR added — below 1.5x is good, above 2x needs attention
- Extend runway by finding customers, not by cutting — cutting at this stage often cuts the discovery capacity you need

## Stage 2: Series A — Scaling What Works

**Funding stage:** $5M–$20M typically.
**Team size:** 10–50 people.
**Primary job:** Build the machine that reliably delivers more of what caused PMF.

Series A is premised on: PMF is found, we're now investing to scale the go-to-market and build repeatable systems. If PMF isn't actually found, Series A just burns more money on a leaky bucket.

**What changes from seed stage:**

*Go-to-market:*
- Hire first sales leader (should be someone who can sell AND build process)
- Define the repeatable sales motion: inbound vs. outbound, average sales cycle, deal size, who the buyer is
- Build pipeline discipline: stages, conversion rates, coverage ratio
- Marketing shifts from founder-led PR/content to demand generation

*Product:*
- First product manager (or founder transitions from IC to PM)
- Roadmap becomes collaborative and strategic, not just "fix what customers complain about"
- Engineering team grows; need basic process (sprints, code review, CI/CD)

*Finance:*
- First finance hire or serious finance function (not just bookkeeping)
- Monthly close < 7 business days
- Board reporting package with actuals vs. plan
- Hiring plan tied to ARR milestones

*People:*
- First HR person often hired at 25-40 people
- Compensation philosophy defined and documented (see `compensation_design.md`)
- Culture becomes explicit — values articulated, not assumed

**The Series A failure mode:**
- Premature scaling: building sales and marketing infrastructure before sales motion is repeatable
- Key person dependency: entire revenue concentrated in founder's relationships
- Hiring for titles: C-suite hired before company is large enough to need a C-suite (over-managed, under-executed)

## Stage 3: Series B — Scaling the Machine

**Funding stage:** $20M–$75M typically.
**Team size:** 50–200 people.
**Primary job:** Prove the unit economics and scale multiple functions simultaneously.

Series B investors want to see:
- CAC payback period improving or holding as you scale
- Net revenue retention (NRR) above 110% — expansion revenue compensating for churn
- Sales efficiency: are reps ramping to quota in a reasonable time?
- Gross margin stability or improvement as you scale

**What changes from Series A:**

*Organization:*
- Functional leaders with real authority (VP-level, not just senior ICs)
- Cross-functional coordination becomes a challenge — product, engineering, sales, marketing, customer success must align
- OKRs or similar planning process needed (see `okr_frameworks.md`)
- First-time management layer — ICs promoted to managers; need manager development

*Go-to-market:*
- Customer success motion built (retention and expansion are now as important as new business)
- Potentially multiple sales segments (SMB vs. mid-market vs. enterprise) requiring different motions
- International expansion often begins at Series B

*Finance:*
- FP&A function (not just accounting)
- Annual operating plan (AOP) tied to board-approved budget
- Scenario planning becomes material (see `scenario_planning.md`)

*Product:*
- Platform thinking begins — extensibility, APIs, integrations, ecosystem
- Technical debt becomes board-level topic
- Enterprise features required: SSO, audit logs, permissions, SLAs

**The Series B failure mode:**
- Second-year sales slump: easy customers are already customers; harder accounts require different sales muscle
- Middle management gap: ICs promoted to managers without coaching; team performance drops
- Founder CEO transition: strong product visionary often needs a COO or President at this stage to run operations

## Stage 4: Series C and Beyond — Towards Durability

**Team size:** 200-1000+ people.
**Primary job:** Build a durable, defensible business.

By Series C, investors are thinking about exits: IPO in 3-5 years, or strategic acquisition. The company needs:

*Governance maturity:*
- Board structure with independent directors (see `board_composition_and_governance.md`)
- Audit committee, compensation committee
- Financial controls approaching public-company standards

*Operational maturity:*
- Predictable forecasting (miss <10% of quarterly plan)
- Strong unit economics at scale
- Multiple revenue lines or product pillars (single-product risk is a valuation discount)

*People maturity:*
- Executive team capable of operating in a public-company environment
- Succession planning for key roles
- Performance management systems that work at scale

*Market position:*
- Defensible moat: network effects, switching costs, proprietary data, brand, regulatory advantages
- Competitive moat analysis reviewed at board level annually

## The Stage-Misalignment Risk

The most common strategic error: running a Series B playbook on a seed-stage company, or a seed-stage playbook at Series B.

| Behavior | Right stage | Wrong when applied at |
|----------|------------|----------------------|
| Do things that don't scale | Seed | Series B — you can't grow with manual process |
| Build process and org structure | Series A+ | Seed — overhead before PMF kills velocity |
| Optimize unit economics | Series B | Seed — you don't have enough data to optimize |
| Multiple GTM motions simultaneously | Series C | Series A — splits focus, confuses the market |
| Heavy executive layer | Series C+ | Seed/A — over-managed, slows decisions |

## Founder Evolution

The skills that got a company to $1M ARR are not the skills that get it to $10M or $100M. Founders who recognize this and adapt outperform those who don't.

- **$0-$1M:** Founder as everything — seller, builder, recruiter, customer support
- **$1-10M:** Founder as sales leader and product visionary; first managers installed
- **$10-50M:** Founder as CEO — set strategy, culture, and executive team; delegate execution
- **$50M+:** Founder as institutional leader — board management, public market preparation, long-term strategy

The transition from builder to executive to institutional leader is hard and not everyone makes it. The companies that go the distance usually have founders who learn to hire people better than themselves in every function, get out of their way, and focus where founder uniqueness (vision, culture, network) adds irreplaceable value.
