# Commercial Contracts

*Note: General educational information, not legal advice. Contract terms have legal consequences that depend on jurisdiction and circumstance — consult licensed counsel for specific decisions.*

## The Standard Document Stack

For B2B SaaS, the standard customer contract structure is:

- **Master Services Agreement (MSA)** — durable terms that apply to the relationship (liability, IP, confidentiality, termination, dispute resolution). Signed once, referenced by all Order Forms.
- **Order Form** — commercial terms for a specific purchase (products, quantities, prices, term length). Signed per deal or renewal.
- **Data Processing Addendum (DPA)** — required by GDPR; defines roles (controller vs. processor), subprocessors, security, cross-border transfers.
- **Service Level Agreement (SLA)** — uptime, support response times, and remedies (typically service credits). Often a schedule to the MSA.
- **Statement of Work (SOW)** — for professional services tied to the SaaS deployment.

Use your paper as the starting point. Negotiating from the customer's paper is more expensive (legal time) and usually worse outcomes.

## The Terms That Actually Matter

Most negotiation time is wasted on terms that don't change outcomes. These are the ones that do:

### Limitation of Liability (LoL)

The cap on damages you can owe under the contract. The single most financially consequential term.

- *Standard*: cap at 12 months of fees paid in the trailing 12 months
- *Pushback you'll see*: 2x or 3x fees, unlimited for certain categories (IP, confidentiality, data breach)
- *Carve-outs that are normal*: gross negligence, willful misconduct, IP indemnification
- *Carve-outs to resist*: data breach (huge exposure), regulatory fines, indemnification claims

Without a cap, a single deal could bankrupt the company. Never sign a contract with no liability cap unless legal has cleared it explicitly and the business case justifies the risk.

### Indemnification

A promise to defend and pay damages for certain claims against the other party. Two common flavors:

- **IP indemnification** (you indemnify customer if your product infringes a third party's IP) — standard in SaaS, usually uncapped or subject to a separate higher cap
- **Mutual general indemnification** (each party indemnifies for breach of confidentiality, gross negligence, etc.) — fair to both sides

**Cap discipline:** indemnification obligations should be tied to your LoL cap, or have their own cap. "Uncapped indemnification" is how a single deal goes catastrophic.

### Data and Security

- *Customer Data ownership*: customer always owns their data. Standard and non-negotiable.
- *Your right to use Customer Data*: limited to providing the service. Be precise about whether you can use it for product improvement, ML training, benchmarking.
- *Security obligations*: usually references a Security Schedule. Avoid open-ended "industry best practice" language — define specific controls or reference SOC 2.
- *Breach notification*: 48-72 hours is increasingly market. Aligns with GDPR.
- *Data return and deletion*: defined timeline (typically 30 days post-termination), customer choice of return format.

### Term and Termination

- *Initial term*: 1-3 years typical; longer term in exchange for pricing discount
- *Renewal*: auto-renewal with N days notice to terminate (60-90 days standard for enterprise; 30 days for SMB). Some jurisdictions require explicit renewal consent.
- *Termination for convenience*: usually NOT granted to the customer for the initial term; if granted, often with early-termination fee
- *Termination for cause*: mutual right to terminate for material uncured breach (typically 30 days to cure)
- *Effects of termination*: refund of prepaid unused fees? Continued data access during transition? Define these explicitly.

### Payment Terms

- *Standard*: net 30 from invoice
- *Enterprise push*: net 60, net 90 — increases working capital burden significantly; consider holding the line or charging for it
- *Late payment*: interest at maximum rate allowed, right to suspend service after N days
- *Disputed amounts*: customer must notify within 30 days or waive — protects you from year-end "audit" disputes

### Assignment and Change of Control

- Standard: each party can assign on change of control without consent
- Customer push: their right to terminate on YOUR change of control (acquisition) — usually grant this for strategic acquirers
- Your protection: their right to assign to a competitor — restrict this

### Most Favored Nation (MFN) — Avoid

A clause that requires you give this customer the best price you give anyone. Sounds harmless. In practice:
- Locks pricing across your entire customer base
- Discoverable in due diligence (acquirers price it as a liability)
- Once granted, very hard to remove

Decline MFN clauses categorically. If pressed, offer a more specific commitment (e.g., "no price increases above CPI for the term").

## NDA Hygiene

NDAs are the most-signed, least-read contracts in business. Treat them seriously.

**Mutual NDAs** for business discussions — both sides protected, fair starting point.

**One-way NDAs** (you sign theirs) require review for:
- Scope of "Confidential Information" — overly broad scope can prevent you from working in adjacent areas
- Non-solicitation clauses — can restrict hiring their employees
- Non-competition clauses — can restrict you from competing in their space (very dangerous in NDAs; usually a sign the other side is trying to capture more than they should)
- Term and survival — confidentiality typically survives 2-5 years; trade secrets survive indefinitely
- Residuals clause — your right to use unaided memory of information; protects future product work

If a customer requires their NDA before a sales conversation, escalate. Most enterprise sales motions can happen under your mutual NDA.

## Contracting Process Discipline

**Templates and playbooks** — maintain a current set of templates and a redline playbook (here's what we'll concede, here's what we won't). Saves enormous time and reduces inconsistency.

**Approval matrix** — what terms can sales agree to without legal? What requires legal? What requires CFO? Document and train sales on it.

**Negotiation log** — track every contract that deviates from template, what we agreed to, why. Builds institutional knowledge and avoids the trap of "we never give discounts on X, except we have, 12 times."

**Self-service for small deals** — sub-$5k or sub-$25k contracts often use clickwrap or simplified Order Form to avoid burning legal time. Define the threshold.

**Contract lifecycle management (CLM) software** — Ironclad, LinkSquares, Juro, Concord — useful at scale (>200 contracts/year). Below that, a well-organized Google Drive plus a tracker spreadsheet works.

## Common Mistakes

1. **Side letters that diverge from MSA** — easy to lose track of; cause renewal disputes years later
2. **Hand-shaking on a term you didn't actually agree** — verbal "we'll figure that out" becomes a $1M argument later
3. **Sales redlining without legal review** — moves deals faster, creates years of liability
4. **Auto-renewal traps** — failing to track customer renewal notice deadlines, losing the customer because no one followed up
5. **Vendor contracts more permissive than customer contracts** — you can't credibly commit to your customer what your vendors haven't committed to you
6. **Free trials with no termination** — a customer trial that quietly continues as a paid service or fails to convert. Define trial terms with clear end dates.

## When to Walk Away

If a customer insists on terms that materially endanger the company, walk. Specifically:
- No liability cap
- Unlimited indemnification with broad scope
- IP assignment of your product (vs. license to use)
- Open-ended audit rights
- Pricing that requires you to operate at a loss

Walking away costs you the deal. Signing costs you the company. The math is obvious in retrospect; harder in the moment when there's quota pressure.
