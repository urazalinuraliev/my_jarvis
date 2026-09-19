# Reading Financial Statements

Three statements, read together, tell the operating story. Read in isolation, each misleads.

## The Income Statement (P&L)

Reports performance over a period (month, quarter, year).

**Standard structure (top to bottom):**

```
Revenue                                $X
   - Cost of Goods Sold (COGS)         (Y)
= Gross Profit                         $A
   - Sales & Marketing (S&M)           (B)
   - Research & Development (R&D)      (C)
   - General & Administrative (G&A)    (D)
= Operating Income (EBIT)              $E
   - Interest Expense                  (F)
   - Taxes                             (G)
= Net Income                           $H
```

**What to actually look at first:**
- **Gross margin** (Gross Profit / Revenue): for SaaS, target 70%+. Below that, investigate COGS — usually overbuilt infrastructure or under-priced services.
- **Operating margin** (EBIT / Revenue): negative is fine for growth-stage; the trajectory matters. Going more negative without offsetting growth is the warning sign.
- **R&D as % of revenue**: 20-40% is typical for growth-stage SaaS; <10% is mature/harvest; >50% is pre-PMF or over-investing.
- **S&M as % of revenue**: 30-50% during growth phase. Watch the magic number to see if it's working.

**Common P&L mistakes:**
- COGS underloaded (excluding customer support, embedded API costs) — inflates gross margin
- One-time items mixed into operating lines — distorts year-over-year comparison
- Capitalized software development hiding real R&D burn — read the cash flow statement to see actual cash R&D

## The Balance Sheet

Reports financial position at a single moment. Always balances: Assets = Liabilities + Equity.

**Assets** (what you own):
- *Current* (convertible to cash within 12 months): cash, accounts receivable, prepaid expenses, inventory
- *Non-current*: PP&E, capitalized software, goodwill, intangibles

**Liabilities** (what you owe):
- *Current*: accounts payable, accrued expenses, deferred revenue (current portion), short-term debt
- *Non-current*: long-term debt, deferred revenue (long-term), lease obligations

**Equity** (owners' residual claim):
- Paid-in capital, retained earnings (cumulative net income), treasury stock

**What to actually look at first:**
- **Cash position** — months of runway at current burn (cash / monthly net burn)
- **Deferred revenue** — for subscription businesses, this is cash collected for services not yet delivered. Growing deferred revenue is a positive signal.
- **Accounts receivable days** (AR / daily revenue) — rising AR days = collection problems
- **Quick ratio** ((Cash + AR) / Current Liabilities) — short-term solvency check; >1.0 is comfortable
- **Goodwill** — large goodwill = past acquisitions. Watch for impairment.

## The Cash Flow Statement

Reports actual cash movement. The most important of the three statements, and the least understood. Three sections:

**Cash Flow from Operations (CFO):**
Starts with Net Income, adjusts for:
- Non-cash items (depreciation, amortization, stock-based comp)
- Changes in working capital (AR, AP, inventory, deferred revenue)
- Result: cash actually generated (or consumed) by running the business

**Cash Flow from Investing (CFI):**
- Capex (PP&E purchases)
- Acquisitions
- Investments in securities
- Almost always negative for growing businesses

**Cash Flow from Financing (CFF):**
- Debt issuance/repayment
- Equity issuance/repurchase
- Dividends paid
- Tracks how the business is funded

**Net change in cash** = CFO + CFI + CFF — this reconciles to the change in cash on the balance sheet.

**Why CFO matters most:**
- Net Income can be positive while cash burns (deferred revenue collected upfront, then service delivered later means high revenue, low cash; the reverse for SaaS is great)
- Working capital changes can mask or amplify the underlying performance
- "Free Cash Flow" = CFO - maintenance Capex. This is what the business produces for shareholders.

## The Three Statements Together — Diagnostic Patterns

| Pattern | What it likely means |
|---|---|
| Revenue growing, gross margin shrinking | Discounting, mix shift to lower-margin products, or COGS scaling badly |
| Net income positive, CFO negative | Aggressive revenue recognition, growing AR, or one-time gains |
| Net income negative, CFO positive | Healthy subscription business (deferred revenue funding burn) — typical for early-stage SaaS |
| Cash growing while burn is reported | New financing, large customer prepayment, AR collection burst, or capex deferral |
| Goodwill rising, organic growth flat | Acquisition spree masking organic stagnation |
| R&D capitalization rising | EITHER real productive investment OR earnings management — investigate which |

## The "Why" Question to Ask Every Quarter

Don't ask "did we hit plan?" Ask: "what did we expect to happen, what actually happened, and what does the variance tell us about our assumptions?"

The financial statements are the result. The variance analysis is where the operating insight lives.
