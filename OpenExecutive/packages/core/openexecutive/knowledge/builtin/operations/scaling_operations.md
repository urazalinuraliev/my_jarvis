# Scaling Operations

## The Scaling Paradox

What got you here won't get you there. The processes, tools, and organizational structures that work at 20 people break at 80. The ones that work at 80 break at 300. Scaling is a continuous process of recognizing which systems have hit their limits and redesigning them — usually while the business is running at full speed.

## The Stages of Operational Maturity

**Stage 1 (1-20 people)**: Everything is informal. Processes exist in people's heads. Communication happens in Slack and ad-hoc meetings. This is fine — don't over-engineer.

**Stage 2 (20-80 people)**: Information starts to fall through the cracks. Onboarding takes too long because knowledge isn't documented. The same problems get solved multiple times. Fix: start documenting processes, build explicit onboarding, establish regular cross-functional meetings.

**Stage 3 (80-300 people)**: Coordination cost becomes a real tax. Decisions that used to happen in a hallway now require meetings. Fix: clear ownership (RACI), decision-making frameworks (when can teams decide vs. escalate), explicit handoffs between functions.

**Stage 4 (300+ people)**: Full organizational design work. Division of responsibilities, spans and layers, management structure. Requires dedicated People Ops and potentially COO-level focus.

## Process Documentation

The test of a good process document: can a new employee follow it on day one without asking anyone?

What to document (prioritize by frequency × cost-of-errors):
- Customer onboarding
- Support escalation paths
- Hiring and interview process
- Sales handoff to customer success
- Incident response
- Vendor procurement

Format that works: step-by-step numbered list, owner for each step, links to tools, decision trees for branches. Avoid paragraphs — no one reads them in a process doc.

Assign a "process owner" to each document who is responsible for keeping it current. Without ownership, documentation becomes stale and unused within 6 months.

## Vendor Management

**Sourcing**: For strategic vendors (significant spend or operational dependency), always run a competitive process — minimum 3 bids. For tactical vendors, the time cost of a competitive process exceeds the savings.

**Negotiation levers**:
- Payment terms (net 30 → net 60 preserves cash)
- Volume commitments (you give committed spend, they give discounted rates)
- Auto-renewal opt-out clauses (critical for SaaS vendors — set a calendar reminder 90 days before renewal)
- SLA and penalty clauses for critical infrastructure vendors
- Exit provisions (how do you get your data out if you switch?)

**Vendor concentration risk**: If a single vendor failure would shut down your business, that's a critical risk. Identify your single points of failure and build redundancy or at least a runbook for failure scenarios.

## Operational Metrics by Function

**Engineering**: Deployment frequency, lead time for changes, change failure rate, mean time to recovery (MTTR). DORA metrics are the standard.

**Sales**: Pipeline coverage (3-5x quota), sales cycle length, win rate, quota attainment, ramp time for new hires.

**Customer Success**: NRR, churn rate, time to first value, NPS/CSAT, support ticket volume and resolution time.

**Finance**: Burn rate, cash runway, AP/AR cycles, forecast accuracy.

## The Rule of Operational Debt

Operational debt accumulates when you skip process steps under pressure. It compounds: deferred documentation means longer onboarding; skipped postmortems mean repeated incidents; informal decisions mean unclear ownership.

Budget explicit time each quarter for operational debt reduction. Typically 10-15% of operational capacity for companies growing >50% annually.
