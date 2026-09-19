# Intellectual Property Strategy

*Note: General educational information, not legal advice. IP law is jurisdiction-specific and highly fact-dependent. Consult IP counsel for material decisions.*

## The Four Pillars of IP

Different IP types protect different things, in different ways, for different durations. A real IP strategy uses several in combination.

### Patents

Protect inventions — novel, non-obvious, useful processes, machines, compositions, or improvements.

- **Utility patents** (most common): 20 years from filing
- **Design patents**: protect the ornamental appearance of an object; 15 years
- **Provisional patents** (US): 12-month placeholder that establishes priority date; allows "patent pending" labeling without full disclosure yet
- Cost: $10-30k per patent (filing through grant) in the US; multiply by jurisdictions for international

**When patents are worth it:**
- Defensible technical innovation that competitors would want to copy
- Industry where patents are weapons (semiconductors, pharma, hardware, deeptech)
- Sufficient capital to litigate — a patent you can't enforce is decoration
- Public filing won't tip your hand to competitors more than the resulting protection is worth

**When patents aren't worth it:**
- Pure software / UI patterns — courts have narrowed software patentability (Alice v. CLS Bank)
- Innovation that will be obsolete within 5 years (the time to first granted patent)
- Early-stage company without budget to enforce
- Trade-secret approach is cleaner (see below)

**Defensive patent strategy:**
- Even if you don't plan to assert, patents deter competitors and provide cross-licensing leverage
- Defensive patent pools (LOT Network, OIN) commit members to non-aggression

### Trade Secrets

Protect commercially valuable information kept confidential. Protection lasts as long as it stays secret — potentially forever (the Coca-Cola formula).

**Requirements:**
- Information has commercial value from being secret
- The owner takes reasonable measures to keep it secret (access controls, NDAs, training, marking)
- Loss of secrecy = loss of protection

**Trade secrets are right for:**
- Algorithms and ML models (where patenting requires disclosure)
- Customer lists and pricing data
- Manufacturing processes
- Recipes and formulations
- Anything where keeping it secret is feasible and disclosure would tip competitors

**Risks:**
- Employee mobility — departing engineers carry trade secrets in their heads; non-competes are unenforceable in California and several other jurisdictions
- Reverse engineering — generally legal in the US; protection doesn't extend to features competitors can deduce from your product
- Forensic recovery — if a trade secret leaks, the legal remedy (Defend Trade Secrets Act in US) is real but slow

**Operational requirements:**
- Document what is and isn't a trade secret
- Access on need-to-know basis only
- Mark confidential materials
- Exit interview includes trade-secret reminder
- Investigate before suing — most "trade secret theft" cases are weaker than they feel

### Trademarks

Protect brand identifiers — names, logos, slogans — that identify the source of goods or services.

- US: TM (claimed mark) anyone can use; ® (registered) requires USPTO registration
- Federal registration costs $250-750 per class plus attorney fees
- Renewable indefinitely with continued use
- International registration via Madrid Protocol

**The strategic point:**
- Trademarks protect the BRAND, not the product
- Strong marks are distinctive (Kodak, Xerox) or arbitrary (Apple for computers)
- Weak marks are descriptive (Best Buy, General Electric) and harder to protect
- Generic marks (escalator, aspirin) lost protection through genericization — risk for hyper-successful brands

**Operational discipline:**
- Search before launching a brand (USPTO TESS, common-law search)
- Register early — first-to-file matters in most jurisdictions
- Police your marks — failure to enforce can weaken protection
- Don't use your trademark as a verb publicly (don't "Google it" — say "search with Google") to avoid genericization

### Copyrights

Protect original works of authorship — code, content, designs, music, video.

- Automatic on creation, no registration required (US)
- Registration ($65) required to sue and to claim statutory damages
- Term: life of author + 70 years (individual); 95 years from publication (corporate works for hire)

**For software companies:**
- Source code is copyrighted; registration provides remedies
- Documentation, marketing copy, website content all copyrighted
- Most useful against blatant copying — competitors who copy chunks of your code or copy

**Work-for-hire and assignment:**
- Employee-created works are owned by the employer (when within scope of employment)
- Contractor-created works are owned by the CONTRACTOR by default unless assigned in writing
- This is the single most-litigated startup IP mistake — see below

## The Core Operational Rule

**All IP created on the company's behalf must be assigned to the company in writing, before the work begins.**

- Every employee signs a PIIA (Proprietary Information and Inventions Agreement) on day one
- Every contractor signs an agreement with an IP assignment clause before they start work
- Founders assign any prior or pre-incorporation IP to the company at formation

Investors check for these in diligence. Missing or weak IP assignment is a deal-killer at Series A and beyond — and often discovered when it's too late and the contractor wants payment to assign.

## Open Source Strategy

If your product uses open source (almost certainly), you must understand the license obligations.

**Permissive licenses** (MIT, BSD, Apache 2.0):
- Can be incorporated into proprietary products
- Attribution and license preservation required
- Generally low operational burden

**Copyleft licenses** (GPL, AGPL):
- Derivative works must be released under the same license
- GPL: linked code becomes GPL-licensed — fatal for many proprietary models
- AGPL: triggers obligation even for SaaS deployment (not just distribution) — generally avoided in commercial SaaS

**License compliance:**
- Maintain a Software Bill of Materials (SBOM)
- Use tools (Snyk, FOSSA, Black Duck) to track dependencies and licenses
- Have an OSS policy that engineers know about

**Releasing your own open source:**
- Pick a license deliberately (Apache 2.0 is most common for permissive corporate OSS)
- Maintain CLA (Contributor License Agreement) so contributions are assigned back to the project
- Open-sourcing parts of your product can be a strategic moat (community, talent, ecosystem) but carries ongoing maintenance cost

## IP in M&A

When acquiring:
- Review IP assignment from every employee and contractor of target
- Audit open-source compliance
- Check for patent assertion risks (NPE suits against target)
- Verify trademark registration and absence of infringement

When being acquired:
- Get your IP assignment, OSS compliance, and trademark portfolio in order BEFORE diligence starts
- Discovered IP issues in diligence depress valuation or kill deals
- Time to fix during a deal process is zero

## IP Disputes — When You're Asserted Against

Receiving a cease and desist or infringement claim is alarming but rarely fatal. Process:

1. **Don't respond emotionally**. Acknowledge receipt, no admissions
2. **Engage counsel immediately**. Statements made before counsel can be used against you
3. **Investigate the claim**. Often weaker than presented
4. **Assess options**: design around, invalidate the patent, license, settle, fight
5. **Disclose appropriately**. If you have D&O insurance, notify; if you have an investor with information rights, notify

The most-asserted patents are often the weakest — assertion is a business model for NPEs, who count on settlement value being cheaper than litigation. Calibrate accordingly.

## Quick Diagnostic

Ask quarterly:
1. Do we have signed IP assignment from every current and past contributor?
2. What is our open-source posture and is it tracked?
3. What trademarks have we filed, and are any of our key brands unprotected?
4. Are there patents we should file before disclosure (product launch, conference talk)?
5. Have we received any IP correspondence we haven't responded to?

If anything is "no" or "unsure," prioritize fixing it before it becomes a deal problem.
