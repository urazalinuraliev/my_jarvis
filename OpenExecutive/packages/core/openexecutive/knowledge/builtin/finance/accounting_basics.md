# Accounting Fundamentals for Executives

Most executives can read a P&L but struggle when the CFO says "we need to discuss the GAAP-to-cash reconciliation." This isn't a failure of intelligence — it's a gap in vocabulary. Accounting is the language of financial truth in business, and executives who can speak it make better decisions and ask better questions.

## The Accounting Equation

Everything in accounting flows from one identity:

**Assets = Liabilities + Equity**

Assets are what the company owns or controls. Liabilities are what it owes. Equity is the residual — what belongs to shareholders after all claims are paid. This equation always balances, by definition. Every transaction affects at least two accounts so the equation stays in balance. This is double-entry bookkeeping.

## The Three Financial Statements and How They Connect

**Income Statement (P&L):**
- Revenue minus expenses = net income over a period
- Accrual-based: recognizes revenue when earned, expenses when incurred — not when cash moves
- Net income flows to equity on the balance sheet via retained earnings

**Balance Sheet:**
- Snapshot at a point in time of assets, liabilities, and equity
- Current vs. non-current: assets/liabilities due within 12 months vs. beyond
- Assets = Liabilities + Equity always holds

**Cash Flow Statement:**
- Reconciles net income to actual cash movement (the P&L is not cash flow)
- Three sections: Operating (core business cash), Investing (capex, acquisitions), Financing (debt, equity raises)
- Profitable companies can run out of cash; cash-flow-negative companies can grow — you need both

**The link:** Net income → Balance sheet equity (retained earnings) → Cash flow reconciles the two

## Accrual vs. Cash Accounting

**Cash accounting:** Revenue recorded when cash received; expenses recorded when cash paid. Simple, but distorts economic reality — you could collect a year of contracts in January and show no revenue for the rest of the year.

**Accrual accounting:** Revenue recognized when earned (service delivered, product shipped); expenses recognized when incurred (work happens, goods received). GAAP requires this for most companies. Creates accounts receivable (earned, not collected) and accounts payable (incurred, not paid).

**Why it matters:** A SaaS company that collects annual contracts upfront shows cash immediately but spreads revenue recognition over 12 months. Net income lags cash. Understanding which you're looking at prevents misreads.

## Revenue Recognition

The rules for when to record revenue. GAAP's ASC 606 defines a five-step model:

1. Identify the contract with a customer
2. Identify the performance obligations (what you promised to deliver)
3. Determine the transaction price
4. Allocate the transaction price to each obligation
5. Recognize revenue when (or as) each obligation is satisfied

**SaaS implications:**
- Subscription revenue is recognized ratably over the subscription period (not at contract signing)
- Professional services recognized as delivered (often over the project period)
- If you sell a bundle (software + implementation + training), allocate the price to each element separately

**Common errors:** Recognizing revenue too early (to hit a quarter), or allocating contract value to future deliverables that get pulled forward. Both create restatement risk and, in extreme cases, securities fraud exposure.

## The Month-End Close

The close is the process of finalizing accounting records for a period. Typical sequence:

**Week 1 of close (or last days of period):**
- Process final invoices and receipts
- Record manual journal entries (accruals, prepayments, allocations)
- Reconcile bank accounts and credit cards
- Reconcile intercompany transactions (if multiple entities)

**Week 2:**
- Reconcile all balance sheet accounts to source records
- Review P&L for anomalies and investigate
- Process depreciation and amortization
- Complete equity roll-forward

**Final:**
- Lock period in ERP
- Produce draft financials
- Controller/CFO review
- Board/investor package preparation

**What the CEO should know:**
- How long does close take (industry standard: 5-7 business days; best in class: 3-4)?
- What's slowing it down (manual processes, data quality, understaffing)?
- What are the key accruals and estimates that require management judgment?

## Accruals and Estimates

Many P&L items are estimates, not exact. Key management estimates:

**Accrued expenses:** Goods or services received but not yet invoiced. Must estimate and record. If you miss them, expenses appear in the wrong period.

**Deferred revenue:** Cash received for services not yet delivered. A liability — you owe the service. Burns down as you deliver. For SaaS, a large deferred revenue balance is a leading indicator of future recognized revenue.

**Bad debt reserve:** Estimate of AR you won't collect. Updated based on aging and customer health.

**Inventory reserves:** Estimate of obsolete or slow-moving inventory to be written down.

**Warranty reserves:** Estimate of future warranty costs for products already sold.

**Stock-based compensation:** Non-cash expense based on Black-Scholes or binomial valuation of options/RSUs. Significant for pre-IPO companies; affects GAAP net income but not cash flow.

These estimates require judgment. Auditors scrutinize them. Aggressive vs. conservative choices materially affect reported results.

## Depreciation and Amortization

**Depreciation:** Allocates the cost of tangible fixed assets (equipment, furniture, leasehold improvements) over their useful life. A $60K server depreciated straight-line over 3 years = $20K/year expense, even though cash was paid upfront.

**Amortization:** Same concept for intangible assets — acquired software, patents, customer lists, non-compete agreements from acquisitions.

**Why it matters:** Capex doesn't hit the P&L immediately; depreciation does. Companies heavy in capex can have strong P&L and weak cash flow (cash went out to buy the asset; P&L sees only the annual depreciation slice).

**EBITDA adds back D&A** precisely because it's a non-cash charge that complicates comparability across companies with different capital structures.

## Working Capital

**Working capital = current assets − current liabilities**

The liquidity available for day-to-day operations. The components:

- **Accounts receivable (AR):** Customer invoices outstanding
- **Inventory:** Raw materials, WIP, finished goods
- **Accounts payable (AP):** What you owe suppliers
- **Accrued liabilities:** Obligations incurred but not yet paid
- **Deferred revenue:** Cash received, service not yet delivered (reduces working capital — it's a liability)

**Cash conversion cycle:** How long cash is tied up in operations
- Days Sales Outstanding (DSO): AR / (Revenue / 365) — how long to collect invoices
- Days Inventory Outstanding (DIO): Inventory / (COGS / 365) — how long inventory sits
- Days Payable Outstanding (DPO): AP / (COGS / 365) — how long you take to pay suppliers
- **CCC = DSO + DIO − DPO**

Lower CCC = faster cash conversion = less working capital needed to support growth. Negative CCC (collect from customers before paying suppliers) is a competitive advantage; Amazon and Walmart have it.

## Audit and Financial Control

**The annual audit:** External auditors issue an opinion on whether financials fairly present the company's position. Three types of opinions:
- *Unqualified ("clean"):* Fairly presented in all material respects — what you want
- *Qualified:* Fairly presented except for specific issues — explains what's wrong
- *Adverse:* Not fairly presented — serious; raises going concern or fraud questions

**What triggers audit scrutiny:**
- Revenue recognition timing
- Related-party transactions
- Management estimates (reserves, intangibles, goodwill)
- Material weaknesses in internal controls
- Significant unusual transactions near period end

**Internal controls:** Policies and processes that prevent errors and fraud. For public companies, SOX 302 and 404 require management and auditor attestations. For private companies, investors and lenders increasingly expect documented controls, especially pre-IPO.

**The executive's role:** Sign management representation letters certifying the financials are accurate. This is not a formality — it carries legal consequence. Ask the CFO to explain the major estimates and judgments you're certifying before signing.

## Common Accounting Red Flags

1. **Revenue recognized before delivery** — accelerating recognition to meet targets
2. **Expense timing manipulation** — deferring legitimate expenses into future periods
3. **Round-number entries** — clean numbers in complex accruals suggest estimates, not calculations
4. **Audit adjustments late in the process** — auditors finding errors the close process should have caught
5. **High DSO creep** — customers paying slower; could signal collection problems or AR quality issues
6. **Large and growing deferred revenue that isn't burning down** — implies revenue isn't being delivered
7. **Restatements** — prior periods restated; indicates control failure; destroys credibility with investors

## The Question Set for Your CFO

Regularly ask:
1. What are the three biggest estimates and assumptions in this period's financials?
2. Where are we most at risk of a restatement if our assumptions prove wrong?
3. How is DSO trending, and are there specific customer collection risks?
4. How close is our close timeline to best practice?
5. What material weaknesses or significant deficiencies did internal or external audit flag?

You don't need to be an accountant. You need to ask the questions that an accountant would expect you to ask.
