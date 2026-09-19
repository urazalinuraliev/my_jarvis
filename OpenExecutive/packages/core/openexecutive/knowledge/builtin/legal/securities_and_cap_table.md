# Securities Law and Cap Table Management

*Note: General educational information, not legal advice. Securities law is complex, fact-specific, and consequential. Engage securities counsel for any equity transaction.*

The cap table is the company's economic constitution. Securities laws govern how it gets created and changed. Both are easy to get wrong in ways that take years to surface and cost millions to fix.

## What Counts as a Security

A security is broadly any investment of money in a common enterprise with an expectation of profits primarily from others' efforts (the Howey Test). This includes:

- Stock (common, preferred)
- Convertible notes
- SAFEs (Simple Agreement for Future Equity)
- Warrants and options
- Phantom equity / stock appreciation rights (sometimes)
- Tokens / crypto assets (often, per SEC enforcement)

**Why it matters:** any time you offer or sell a security, federal and state securities laws apply. Either register the offering with the SEC (expensive, rare for private companies) or qualify for an exemption.

## Common Exemptions for Private Companies

**Regulation D — the main exemption:**
- *Rule 506(b)*: unlimited capital from accredited investors + up to 35 non-accredited "sophisticated" investors; no general solicitation
- *Rule 506(c)*: unlimited capital from accredited investors only; general solicitation allowed if accreditation verified
- *Rule 504*: smaller capital limit ($10M), some state-level restrictions

**Accredited investor definition** (US, simplified):
- Individuals: $200k annual income ($300k joint) for 2 years OR $1M net worth excluding primary residence
- Entities: $5M+ in assets, or all owners accredited
- New categories (post-2020): certain professional certifications (Series 7, 65, 82)

**State "blue sky" laws:**
- Notice filings required in each state where investors reside
- Form D filing with SEC + state notices
- Easy to forget; consequences include rescission rights for investors

**Other exemptions:**
- *Regulation A+*: up to $75M, lower-cost than IPO; growing in popularity
- *Regulation Crowdfunding*: up to $5M from non-accredited investors via crowdfunding portals
- *Rule 701*: equity to employees and consultants; cap on amount tied to revenue/assets

## Cap Table Structure

The cap table tracks who owns what.

**Components:**
- *Authorized shares*: maximum the company can issue (set in the charter)
- *Issued and outstanding shares*: actually held by stockholders
- *Reserved for issuance*: options granted (not exercised) + options reserved (not granted)
- *Fully-diluted shares*: outstanding + all options + warrants + convertible securities, as if all converted

**Stock classes:**
- *Common stock*: founders, employees; subordinate to preferred in liquidation
- *Preferred stock*: investors; each round typically a new series (Series Seed, A, B, etc.) with priority based on issuance order

**Preferred stock preferences:**
- *Liquidation preference*: investor gets X times their investment back before common gets anything (1x non-participating is market)
- *Anti-dilution*: protection if future rounds are at lower valuation (broad-based weighted average is market)
- *Dividend rights*: usually non-cumulative; rarely paid in cash
- *Voting rights*: typically vote with common as-converted; some matters require separate preferred vote
- *Conversion*: each preferred share converts to N common shares (usually 1:1 initially)
- *Protective provisions*: investor approval required for certain actions

## SAFEs and Convertible Notes

Common pre-priced-round financing instruments.

**SAFE (Simple Agreement for Future Equity):**
- YC-popularized
- No interest, no maturity date
- Converts to preferred stock at next priced round
- Key terms: *valuation cap* (maximum valuation at which SAFE converts) and *discount* (discount to next round's price)
- Post-money SAFE (current standard): valuation cap is on post-money basis

**Convertible Note:**
- Debt instrument (technically a loan)
- Interest (typically 2-8%) accrues until conversion
- Maturity date (typically 18-24 months)
- Converts at next priced round (or matures, requiring repayment or extension)
- Key terms: interest rate, maturity, valuation cap, discount

**Practical differences:**
- SAFEs simpler; convertible notes more contract-like (lenders' rights)
- SAFEs preferred for early-stage given simplicity
- Convertible notes used when investor wants debt characteristics (often later-stage bridge financing)

**Cap table impact of SAFEs/notes:**
- Until conversion, they're not technically on the cap table as shares
- BUT they will convert and dilute existing holders
- Critical to model the as-converted cap table when raising the priced round — surprise SAFEs can materially affect post-round ownership

## Equity Grants to Employees

Equity is regulated. Granting it requires care.

**Stock options:**
- Right to buy stock at a fixed price (exercise price) in the future
- Two types in US: ISO (Incentive Stock Option) and NSO (Non-Qualified Stock Option)
- *ISO*: tax-advantaged for employees IF holding requirements met; $100k vesting limit per year per employee
- *NSO*: ordinary income on exercise of spread; no holding requirements; required for contractors and 10%+ shareholders

**Restricted Stock Units (RSUs):**
- Promise to issue stock when vesting conditions met
- Income on vesting (cash needed for tax withholding)
- More common at later stage (typically post-Series-C)

**Restricted Stock:**
- Stock issued upfront, subject to repurchase right if vesting unmet
- Typical for founders
- 83(b) election within 30 days to lock in cost basis at low value

**409A valuations:**
- Required to set exercise price for stock options (must be at or above "fair market value")
- Independent appraisal (typically annual, or after material events)
- Failure to set FMV correctly: penalty taxes on employee (20%+ federal); company liability

**Granting discipline:**
- Board approval for every grant
- Grant documentation: notice of grant + agreement
- Track vesting schedules per employee
- 409A refresh after material events (new round, big customer signing, M&A signing)
- Carta, Pulley, or equivalent platform to track

## Common Cap Table Mistakes

**1. Promising equity verbally without documenting**
- "We told the employee they'd get 0.5%"
- Later: dispute over what was promised, when vesting started, what the valuation was
- *Cure*: every grant documented at signing, before work starts

**2. Missing 83(b) elections**
- Founder or employee receives restricted stock, doesn't file 83(b) within 30 days
- Pays ordinary income tax as shares vest (potentially on high values)
- Irrecoverable after 30 days
- *Cure*: file 83(b) immediately on grant; track filing

**3. Improper grant approval**
- CEO or HR granting options without board approval
- Grants invalid; can require board ratification + 409A repricing
- *Cure*: board approval for every grant (can be done by unanimous written consent)

**4. Incorrect 409A pricing**
- Setting exercise price below FMV
- Employee tax penalty; company liability for taxes/penalties
- *Cure*: current 409A; conservative pricing

**5. Stale cap table**
- Spreadsheet not updated; recent grants missing; transfers untracked
- M&A diligence reveals discrepancies; deal delayed or re-priced
- *Cure*: cap table software; quarterly reconciliation

**6. Side letters proliferating**
- "MFN rights" with one investor; "investment rights" with another
- Each investor has unique terms; conflicts arise
- *Cure*: standardize terms; resist side letters; if granted, track meticulously

**7. Surprise dilution from convertibles**
- SAFEs from prior rounds not properly modeled; conversion at next round materially dilutes existing holders
- Founders thought they owned 50%; discover they own 35% post-round
- *Cure*: model conversion at every fundraise; communicate to founders before signing new round

## Public Company Implications

When considering an eventual IPO or M&A:

**Cap table cleanliness:**
- Every grant documented
- 409A history defensible
- No undisclosed promises
- All option pool exercises and forfeitures accounted for

**Securities offering history:**
- Each prior round documented and securities exemptions confirmed
- Form D filings made
- State notice filings completed
- Any unregistered securities (e.g., promised but not formally granted) cleaned up

**Insider transactions:**
- All affiliated party transactions disclosed and approved
- Loans to executives prohibited post-Sarbanes-Oxley
- Repurchases of executive stock subject to scrutiny

Pre-IPO companies often discover cap table problems requiring expensive (sometimes painful) remediation. The earlier this is addressed, the cheaper.

## Insider Trading Rules

Even private companies have rules.

**Material non-public information (MNPI):**
- Insider trading laws apply once shares trade in secondary markets
- Officers, directors, large shareholders, and employees with MNPI have restrictions
- Secondaries (employees selling to outside investors) must comply
- Tipping (sharing MNPI with others who trade) is also a violation

**Once public:**
- Section 16 reporting for officers/directors
- 10b5-1 plans for systematic selling
- Blackout windows around earnings
- Rule 144 limits on insider sale volume

**Internal compliance:**
- Insider trading policy
- Quiet periods
- Pre-clearance for executive trades
- Annual training

## The Cap Table Diagnostic

Annually (and before any major transaction):
1. Is our cap table current — all grants, transfers, exercises reflected?
2. Are all 409A valuations current and defensible?
3. Have all Form D and state notice filings been made for past rounds?
4. Are there any verbal promises of equity not yet documented?
5. What does our fully-diluted cap table look like after all SAFEs and notes convert?

If you can't answer #5 quickly with confidence, you're not actually in control of your cap table.
