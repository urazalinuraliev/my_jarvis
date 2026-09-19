# Procurement and Vendor Management

The procurement function is widely misunderstood. It's not "the people who say no" or "the gatekeeper of POs." Done well, procurement is a strategic discipline that reduces cost, manages risk, and protects against vendor failures. Done badly, it slows the business and creates workarounds.

## What Procurement Actually Does

Three primary jobs:

1. **Sourcing** — finding and selecting the right vendors
2. **Negotiating** — contracting on favorable terms
3. **Vendor management** — managing relationships, performance, risk

In smaller companies, this is part of someone's role (CFO, COO, or finance manager). At ~$50M ARR, it justifies a dedicated procurement function. At ~$200M ARR, it's a small team.

## The Procurement Lifecycle

For any meaningful purchase (typically >$10-25k or any strategic vendor):

**1. Need definition**
- What problem are we solving?
- What's the must-have functionality?
- What's the must-have ROI?

**2. Market scan**
- What vendors exist?
- What category benchmarks apply?
- What does the build vs. buy vs. partner analysis say?

**3. Vendor selection**
- Shortlist (typically 3-5)
- RFP or structured evaluation
- Demos, references, security review
- Decision criteria documented; choice made

**4. Negotiation**
- Commercial terms (price, term, payment)
- Legal terms (liability, IP, data, termination)
- Operational terms (SLA, support, implementation)

**5. Contracting**
- MSA + Order Form (typical for SaaS)
- Approvals per authority matrix
- Signatures and storage

**6. Onboarding and operationalization**
- Implementation
- User adoption
- Integration with existing systems

**7. Ongoing management**
- Performance review
- Renewal preparation
- Issue escalation

**8. Renewal or replacement**
- Decide before notice deadline
- Negotiate or transition

Skipping any step is how costly mistakes happen. The most-skipped steps: market scan (so you over-pay for incumbent), reference checks (so you discover problems post-purchase), renewal preparation (so you auto-renew at unfavorable terms).

## Sourcing Discipline

**Three-bid rule:**
- For purchases >$25k or strategic vendors, get at least 3 bids
- Forces market comparison
- Even when you know who you'll choose, the bids inform negotiation leverage

**RFP (Request for Proposal):**
- For complex purchases (>$100k, strategic, multi-year)
- Structured document: requirements, evaluation criteria, timeline, format for response
- Levels the playing field; surfaces capability differences

**RFI (Request for Information):**
- Earlier in the process; explores the market
- Less formal than RFP
- Use to narrow shortlist before RFP

**The vendor selection scorecard:**
- Functional fit (does it solve our problem?)
- Total cost of ownership (not just license cost)
- Implementation cost and time
- Integration with existing stack
- Vendor stability (will they exist in 3 years?)
- Security posture
- Reference quality
- Cultural fit / partnership potential

Weight the criteria explicitly. Score each vendor. Document the choice. Six months from now when someone questions the decision, you'll have the rationale.

## Negotiation Levers

The terms that move materially in negotiation:

**Price:**
- Discount % off list
- Multi-year commitment for incremental discount (be careful — locks in choice)
- Volume discounts at scale
- "Last seat" or "round number" psychology

**Payment terms:**
- Net 30, 60, 90 (longer = preserves your cash; vendor may push back)
- Quarterly or monthly billing vs. annual upfront
- Prepayment discounts (cash now in exchange for price reduction)

**Term length:**
- 1-year, multi-year
- Auto-renewal vs. opt-in renewal
- Termination for convenience (you can exit) — often refused but worth asking
- Notice period for termination

**Pricing escalators:**
- Caps on annual increases (CPI + 3%, etc.)
- Locked pricing for full term
- Sometimes both: locked for term, capped after

**SLA and credits:**
- Uptime commitments
- Service credits for misses (often 5-25% monthly fee per missed tier)
- Right to terminate for repeated breach

**Audit rights:**
- For vendors handling sensitive data: customer audit rights, third-party audit rights, SOC 2 reports
- For software: license usage audit rights (negotiate scope and frequency)

**Implementation:**
- Free implementation (or capped fees)
- Onboarding support
- Training included

**Data and exit:**
- Data export at end of contract (specific format, timeline)
- Data deletion certification
- Source code escrow (for custom development)

**Most-Favored Nation (MFN) — be careful:**
- Locks you to the lowest price they give anyone
- Usually wanted by the vendor (commits you to their list)
- Sometimes wanted by you (commits them not to undercut your price)
- In either direction, complicates the future

**The discipline:** know which terms matter most before negotiating. The vendor knows. If you don't, you'll trade away what matters for what doesn't.

## Strategic vs. Tactical Vendors

Tier your vendors. Not all deserve equal attention.

**Strategic vendors:**
- Material spend (typically >$500k annually)
- Mission-critical (failure would significantly disrupt operations)
- Long-term relationship (multi-year contracts, deep integration)
- Examples: cloud infrastructure (AWS), CRM (Salesforce), payments (Stripe)

**Tactical vendors:**
- Routine spend (typically <$50k annually)
- Easily substitutable
- Short contracts or month-to-month
- Examples: most SaaS subscriptions, office supplies, contractors

**Strategic vendor management:**
- Named relationship owner on your side
- Named account team on their side
- Quarterly business reviews (QBRs)
- Joint planning and roadmap alignment
- Executive sponsorship on both sides

**Tactical vendor management:**
- Self-service contracting where possible
- Annual usage and cost review
- Bulk renewal cycles
- Minimal individual attention

The mistake: treating tactical vendors strategically (wasted time) or strategic vendors tactically (gaps in oversight when things break).

## Vendor Risk Management

For any vendor with access to data, systems, or significant spend:

**Onboarding security review:**
- SOC 2 Type II report (or equivalent)
- Data Processing Agreement (DPA) if processing personal data
- Cybersecurity questionnaire (SIG, CAIQ, custom)
- Insurance certificates (cyber, errors & omissions, general liability)
- Subprocessor list

**Ongoing risk monitoring:**
- Annual SOC 2 refresh
- Notification of material changes (subprocessors added, security incidents, certifications lost)
- Vendor health monitoring (financial stability, key personnel changes, M&A)

**Concentration risk:**
- Identify vendors where failure would significantly disrupt operations
- For each: contingency plan, alternative options, transition timeline
- Avoid single-vendor lock-in for mission-critical capabilities

**The "what if they disappeared" exercise:**
- For each strategic vendor: what happens if they're acquired, breached, or shut down?
- Plan for the failure even if you can't prevent it
- See `business_continuity.md`

## Contract Management

**Central contract repository:**
- All executed contracts in one place
- Metadata: vendor, type, value, term dates, key terms (auto-renewal, notice period, MFN)
- Searchable; accessible to legal, finance, procurement
- Tools: Ironclad, LinkSquares, Concord, Juro at scale; Google Drive + spreadsheet for smaller

**Renewal calendar:**
- 90, 60, 30-day reminders before notice deadline
- Renewal decision-maker named for each contract
- Renewal preparation: usage analysis, vendor performance, market alternatives, negotiation strategy

**Auto-renewal trap:**
- Vendor auto-renewal with 30-90 day notice required
- Missing the deadline = locked in for another year at standard price increase
- Calendar discipline is the entire defense

## Spend Management

**Approval matrix:**
- Defines what spend requires what level of approval
- Example: <$5k department head; $5-25k VP; $25-100k C-suite; >$100k CEO + CFO
- Approval triggered by purchase order or contract submission

**Spend categories:**
- Software (SaaS subscriptions) — often the largest non-payroll line at tech companies
- Cloud infrastructure
- Marketing programs and ad spend
- Professional services and consultants
- Office (rent, utilities, supplies)
- Travel and events
- Hardware

**Cost optimization patterns:**
- *SaaS sprawl audit*: identify duplicate / underutilized tools (typically 20-30% of SaaS spend)
- *Cloud cost optimization*: rightsizing, reserved instances, savings plans
- *Vendor consolidation*: bundling spend with fewer vendors for better terms
- *Off-cycle renegotiation*: renegotiating in market downturns when vendors are softer

## SaaS-Specific Procurement

SaaS has unique characteristics:

**The SaaS proliferation problem:**
- Departments buy with credit cards; finance doesn't see the spend
- Shadow IT: tools used without IT/security review
- Duplicates: marketing uses one tool, sales uses another, doing the same thing

**The SaaS audit:**
- Annual review of every SaaS tool: who's using it, what does it cost, what's the renewal date, can we consolidate?
- Tools: Vendr, Tropic, Cledara, manual spreadsheets
- Findings: typically 15-30% savings opportunity in first audit

**Renewal cycles:**
- Most SaaS auto-renews
- Most SaaS price-escalates 5-15% per year
- Most SaaS over-licenses (you bought 100 seats, you use 70)
- Each renewal is a negotiation opportunity if you prepare

## Common Procurement Failures

1. **No approval matrix** — anyone with a credit card buys anything; finance discovers later
2. **Single bids** — incumbency wins by default; pricing becomes vendor's choice
3. **Auto-renewal cascade** — missing deadlines locks the company into unfavorable terms
4. **Security review skipped** — vendor breach exposes customer data; "we didn't know"
5. **No central contract repo** — same contract negotiated three times; terms diverge
6. **Strategic vendor neglect** — relationship breaks down at QBR; both sides surprised
7. **Tactical vendor over-management** — wasting procurement time on $5k contracts

## The Procurement Diagnostic

For your spend, ask:
1. What's our top 10 vendor list by spend? Do we know each renewal date?
2. What % of strategic vendors had a real renewal negotiation in the past year (vs. auto-renewal)?
3. What's our concentration risk? Which 1-2 vendor failures would hurt most?
4. How many SaaS tools do we pay for? When did we last audit for duplication?
5. What's our approval matrix? Is it followed?

If you can't answer #1 quickly, procurement isn't really happening — purchases are happening, but no one is managing the function.
