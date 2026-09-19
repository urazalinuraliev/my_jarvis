# Data Privacy and Security

*Note: This document provides general educational information. It is not legal advice. Data privacy law varies by jurisdiction and changes frequently — consult licensed counsel for decisions affecting your company.*

## Why This Matters for Operators

Privacy and security obligations have moved from "lawyer thing" to "deal blocker." Enterprise customers will not buy from vendors who can't answer their security questionnaires. Regulators in the EU, California, and increasingly elsewhere impose meaningful fines. A breach costs you customers, executives, and sometimes the company itself.

## The Major Regulatory Regimes

**GDPR (EU General Data Protection Regulation)** — applies if you process personal data of EU residents, regardless of where your company is based.
- Personal data is broadly defined: name, email, IP address, device IDs, location data, behavioral data
- Six lawful bases for processing — consent is one, but not always the easiest (legitimate interest, contract performance, legal obligation often more practical)
- Data subject rights: access, deletion, portability, rectification, objection — must respond within 30 days
- Fines up to 4% of global annual revenue or €20M, whichever is higher
- Requires Data Processing Addenda (DPAs) with all vendors that touch EU personal data
- Cross-border data transfer requires Standard Contractual Clauses (SCCs) or adequacy decision

**CCPA / CPRA (California)** — applies to companies meeting size thresholds processing California residents' data.
- Right to know, delete, opt out of sale, and (under CPRA) limit use of sensitive personal information
- Required "Do Not Sell or Share My Personal Information" link on websites
- Lower bar than GDPR but increasingly aligned

**HIPAA (US healthcare)** — applies to covered entities (providers, plans, clearinghouses) and their business associates.
- Protected Health Information (PHI) gets strict handling rules
- Requires Business Associate Agreements (BAAs) with any vendor that touches PHI
- Avoid being a covered entity if your product doesn't require it — the compliance burden is high

**Other regimes to be aware of:** PIPEDA (Canada), LGPD (Brazil), PDPA (Singapore), DPDP (India), state laws (Virginia, Colorado, Connecticut, Utah, Texas — list growing)

**Sector-specific:** GLBA (financial services), FERPA (education), COPPA (children under 13)

## SOC 2 — The De Facto Enterprise Security Bar

SOC 2 is an audit framework, not a regulation. Enterprise customers (especially in financial services, healthcare, and large tech) routinely require SOC 2 Type II reports before signing.

**Two types:**
- **Type I**: point-in-time audit of controls as designed
- **Type II**: audit of controls operating effectively over 6-12 months — this is what enterprise expects

**Five Trust Service Criteria** (Security is required, others optional):
1. Security (always required)
2. Availability (uptime commitments)
3. Confidentiality (data classification, access controls)
4. Processing Integrity (correct data processing)
5. Privacy (PII handling)

**Practical timeline for first SOC 2 Type II:**
- 3-6 months to implement controls (policies, access management, monitoring, vendor management)
- 6 months observation period
- 4-8 weeks for auditor fieldwork and report

Vendors like Vanta, Drata, Secureframe automate ~70% of the evidence collection. Use them — manual SOC 2 is a full-time job.

**ISO 27001** — international analog. Required by many European and Asian customers. Often pursued alongside SOC 2.

## Common Operational Requirements (Whatever Your Regime)

**Data Processing Inventory:**
- What personal data do we collect, why, how long do we retain it, who do we share it with?
- This is the foundation document for GDPR, CCPA, and most privacy regimes
- Update quarterly or when material changes happen

**Privacy Policy and Terms:**
- Privacy policy must reflect actual practices (not aspirational)
- Mismatch between stated and actual practice is a regulatory and PR risk
- Review annually; update when products or vendors change

**Vendor Management:**
- DPA with every vendor processing personal data
- Track subprocessors (vendors of your vendors) — required disclosure under GDPR
- Annual review of vendor SOC 2 reports or equivalent

**Incident Response Plan:**
- Documented process for detection, containment, investigation, notification
- Notification timelines vary: GDPR is 72 hours to regulators, many US states 30-60 days to individuals
- Test the plan annually with a tabletop exercise — first run reveals gaps

**Data Subject Request (DSR) Handling:**
- Process to receive, verify identity, locate data, fulfill within deadline (30 days GDPR, 45 days CCPA)
- Many requests are simple deletes; some are complex (data spread across multiple systems)
- Track DSRs — pattern of requests can signal product or marketing issues

## Security Controls — The Baseline Operators Should Maintain

Even pre-SOC 2, the following controls are table-stakes and customer questionnaires assume them:

1. **MFA on all production systems and admin accounts** — non-negotiable
2. **SSO for employee access to internal tools** — reduces attack surface, simplifies offboarding
3. **Role-based access controls** with periodic access reviews (quarterly)
4. **Encryption in transit (TLS 1.2+) and at rest** for all customer data
5. **Centralized logging and monitoring** with retention (90+ days minimum)
6. **Endpoint security** on employee devices (MDM, EDR)
7. **Background checks** on employees with production access
8. **Security awareness training** — annual, plus phishing simulations
9. **Vulnerability management** — automated scanning, defined SLAs for patching
10. **Backup and disaster recovery** — tested annually, RPO/RTO defined

## Privacy and Security in the Product

Build these in early; retrofitting is expensive.

**Data minimization** — collect only what you need. The data you don't have can't be breached, requested, or regulated.

**Purpose limitation** — use data only for the purpose for which it was collected. Don't quietly repurpose for marketing or model training.

**Pseudonymization** — separate identifiers from behavioral data. Reduces breach severity and supports analytics.

**Region pinning** — for EU customers, ability to keep data in EU. Increasingly required for enterprise deals.

**Tenant isolation** — multi-tenant SaaS should enforce isolation at the database/storage layer, not just at the application layer. Tested cross-tenant access is a critical security review item.

**AI/ML considerations** — if you train on customer data, the consent and notice requirements are strict. If models can memorize and regurgitate training data (LLMs), that's a privacy risk to design against.

## Breach Response — When (Not If)

Most breaches are small, contained, and never public. But every operator should have a plan that assumes the breach is real, large, and discovered first by a journalist.

**Hour 1:**
- Containment — stop the bleed
- Activate incident response team (security, legal, comms, exec)
- Preserve evidence (logs, snapshots) — destroyed evidence becomes a regulatory and litigation problem

**Day 1-3:**
- Forensics — what was accessed, by whom, when
- Legal review of notification obligations
- Customer comms drafted (do not publish until forensics gives a stable picture)

**Day 3-30:**
- Regulator and customer notifications (per jurisdictional deadlines)
- Public communication if material
- Remediation of the root cause
- Post-incident review — published internally, summary published externally if appropriate

**The two failure modes to avoid:**
1. Hiding the breach — modern forensics and regulator powers usually surface it eventually; the cover-up is worse than the breach
2. Over-promising in initial comms — early estimates change; better to under-promise and update

## Quick Diagnostic

If asked "are we compliant?", the right answer is never "yes." It's:
1. Which regulations apply to us, given our customers and data?
2. For each, do we have documented evidence of the required controls?
3. When was the last independent review (SOC 2, pen test, GDPR audit)?
4. What are our top 3 open compliance risks and what's the plan?

If you can't answer those four, you're not compliant — you just haven't been tested yet.
