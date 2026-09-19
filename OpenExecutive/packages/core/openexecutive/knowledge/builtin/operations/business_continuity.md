# Business Continuity and Incident Response

The companies that survive disruption are not the ones with the best plans. They're the ones with rehearsed plans, named owners, and the discipline to invest before the disruption happens.

## The Three Disciplines

**Business Continuity (BC)** — keeping operations running through a disruption (or restoring them quickly). Covers people, processes, and the supply chain.

**Disaster Recovery (DR)** — specifically about restoring IT systems and data after a failure. A subset of BC.

**Incident Response (IR)** — the operational response when something goes wrong, from a minor outage to a major breach.

The three overlap. Mature organizations have unified plans across them.

## Risk Categorization

Before planning, identify what you're planning for. Common categories:

- **Infrastructure**: data center failure, cloud provider outage, network failure, power
- **Cybersecurity**: breach, ransomware, DDoS, insider threat
- **Application**: software bug, bad deploy, data corruption
- **People**: key person loss (illness, departure, death), strike, mass attrition
- **Supply chain**: vendor failure, geopolitical disruption, single-source supplier
- **Physical**: fire, flood, earthquake, severe weather, pandemic
- **Regulatory**: license loss, sanction, sudden compliance change
- **Reputational**: viral negative event, executive scandal

For each, define: **likelihood** (low/medium/high) and **impact** (operational, financial, customer, reputational). The product determines priority.

## Recovery Objectives — RPO and RTO

Two numbers anchor every BC/DR plan:

- **RPO (Recovery Point Objective)**: how much data you can afford to lose. "Last 4 hours of transactions" or "last 5 minutes."
- **RTO (Recovery Time Objective)**: how long you can be down. "1 hour" or "8 hours" or "next business day."

Lower RPO/RTO costs more. Define per system, not company-wide:
- Customer-facing transactional systems: RTO minutes, RPO seconds
- Internal analytics: RTO hours-to-days, RPO hours
- Archival systems: RTO days, RPO days

Common failure: setting aggressive RTOs without funding the architecture to deliver them. The plan promises 1-hour RTO; the actual restoration takes 18 hours because the backups have never been tested in a real recovery.

## The BC Plan — What's Actually In It

A working BC plan is not a 200-page binder. It's a focused document covering:

**1. Crisis activation triggers**
- What events trigger the plan (system outage > N minutes, breach detected, etc.)
- Who has authority to activate (and their backups, by name)

**2. Crisis team roster**
- Crisis leader (typically a senior executive)
- Communication leader (single voice to customers and press)
- Technical leader (eng, infra)
- Legal lead
- HR lead (for people events)
- Executive sponsor (board contact)
- All roles named with primary and two backups

**3. Communication plans**
- Internal: how employees are notified (Slack, SMS, phone tree)
- Customer: pre-drafted templates for common scenarios
- Press: spokesperson designated, holding statement prepared
- Regulators: notification obligations and timelines (varies by industry)

**4. Per-scenario playbooks**
- Top 5-10 scenarios with step-by-step response actions
- Most companies focus on: extended cloud outage, data breach, ransomware, key vendor failure, key-person loss

**5. Recovery procedures**
- Per-system DR runbooks
- Order of restoration (which systems first)
- Data validation procedures

**6. Decision authorities**
- What decisions can be made by whom under crisis
- E.g., "CTO can authorize emergency vendor spend up to $50k; CFO above"

## Pre-Drafted Customer Communications

When something is on fire, you don't have time to write good copy. Pre-draft for common scenarios:

**Outage notification template:**
- Acknowledge the issue (what's affected, when started)
- What we're doing about it
- ETA for next update (specific time, not "shortly")
- Apology

**Status page discipline:**
- Status page is the source of truth, not Twitter
- Update at the cadence you promised (every 30 min during major incident)
- Post-mortem published within 5 business days (publicly for major incidents)

**Breach notification template:**
- What happened (specific, no speculation)
- What data was affected (specific)
- What we're doing about it (concrete actions, not generic platitudes)
- What customers should do (clear, actionable steps)
- How to reach us with questions

The first communication shapes the narrative for weeks. Investing time in templates is investing in your reputation during crisis.

## Incident Response Process

For technology incidents (outages, security events, data issues), a standard incident response process:

**Severity definitions:**
- **SEV1**: full or major outage, security breach affecting customers, data loss
- **SEV2**: significant degradation, security issue without customer exposure, partial outage
- **SEV3**: minor degradation, internal-only issue
- **SEV4**: cosmetic, low-impact

**On-call structure:**
- Primary on-call: first responder
- Secondary on-call: escalation if primary unreachable in 5 minutes
- Manager on-call: escalation for SEV1/SEV2
- Executive on-call: for SEV1 lasting >1 hour or customer comms

**Incident commander role:**
- Single person owning the response coordination (not necessarily the most senior)
- Their job is coordination, not solving — solving is done by SMEs
- Rotates between trained ICs

**War room discipline:**
- Single communication channel (incident-specific Slack channel)
- Status updates every 15-30 minutes
- All material decisions logged with timestamp
- No side conversations — keep it all in the channel

**Postmortem (blameless, within 5 business days):**
- Timeline (with timestamps)
- Root cause (not root person)
- Impact (customer, internal, financial)
- What went well
- What didn't
- Action items (owned, dated, tracked to completion)

## Vendor Concentration and Single Points of Failure

Audit your operational dependencies. Look for:

- **Single-vendor dependencies** — if this vendor disappeared, would we be down? For how long?
- **Single-person dependencies** — if this person disappeared, what knowledge would we lose?
- **Single-region dependencies** — if this AWS region went down, what fails?
- **Single-integration dependencies** — if Stripe (or whatever) had an extended outage, what stops?

For each critical dependency:
- Document what we'd do if it failed (even at slower performance or higher cost)
- Where viable, build redundancy or contingency
- Where redundancy isn't viable, accept the risk explicitly (don't pretend it's mitigated)

## Cyber-Specific Continuity

Cyber incidents have their own playbook because the time pressure is asymmetric.

**Detection:**
- Centralized logging and monitoring
- SIEM or equivalent alerting
- Threat intelligence feeds
- Annual penetration testing

**Containment:**
- Isolate affected systems quickly (preserve evidence, but stop the bleed)
- Revoke compromised credentials
- Patch the vulnerability before re-enabling

**Investigation:**
- Forensic preservation of logs and disk
- Often requires external firm (Mandiant, CrowdStrike, Stroz Friedberg)
- Don't destroy evidence by restoring too quickly

**Notification:**
- Regulators per applicable rules (GDPR 72 hours, US state laws vary 30-60 days)
- Customers per contractual obligations
- Insurance carrier (notify quickly to preserve coverage)
- Public disclosure if material

**Cyber insurance:**
- Covers some incident costs (response, notification, credit monitoring)
- Doesn't cover everything (typically excludes acts of war, certain insider acts)
- Premiums and deductibles rising; read the policy actually, not the summary

## Testing the Plan

Untested plans fail. Test before you need to use them.

**Tabletop exercises** (quarterly):
- 90-minute scenario walkthrough with the crisis team
- Facilitator presents events, team responds
- Reveals gaps in: roles, communication channels, decision authorities, vendor dependencies
- Cheap, low-risk, high-value

**DR drills** (annually):
- Actual restoration from backups in a non-prod environment
- Tests technical recovery, not just paper plans
- Reveals: backup integrity, restoration time, missing documentation

**Red team exercises** (annually for mature orgs):
- External team attempts breach without notice
- Tests detection, response, and the full crisis chain
- Expensive but illuminating

Companies that don't test their plans discover the gaps during the actual incident. The cost of testing is always less than the cost of failing.

## Diagnostic — How Prepared Are We?

Ask:
1. If our primary data center / cloud region went down right now, what's our RTO? Have we tested it?
2. If our CEO became unavailable for 30 days, who handles board, fundraising, executive decisions?
3. If our top three vendors each failed for a week, which would hurt most and what's our backup?
4. When was the last tabletop exercise? What did we learn?
5. Where is our incident playbook? Can a new exec find it within 5 minutes?

If you struggle to answer any of these, you have a continuity gap. Most companies have several.
