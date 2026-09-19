---
domain: finance
topic: risk_management
company: Silicon Valley Bank
year: 2023
failure_type: [duration_mismatch, interest_rate_risk, bank_run, regulatory_failure, concentrated_depositor_base]
---

# Silicon Valley Bank Collapse (2023)

## Situation

Silicon Valley Bank (SVB) was the 16th-largest US bank and the primary banking partner for approximately half of all US venture-backed technology companies. Founded in 1983, SVB had built a specialty franchise: it banked startups, their founders, and their VC investors, offering services and terms that mainstream banks did not. By 2021 SVB's deposits had more than doubled to $189 billion, driven by the flood of venture capital into tech companies during the pandemic era. SVB deployed those deposits into long-dated US Treasuries and mortgage-backed securities to capture yield.

## What Happened

When the Federal Reserve began aggressively raising interest rates in 2022, the market value of SVB's long-dated bond portfolio fell sharply. SVB was sitting on unrealized losses of approximately $15 billion — more than its entire equity base. In March 2023, SVB announced it had sold $21 billion of securities at a $1.8 billion loss and needed to raise capital. The announcement triggered panic among SVB's uniquely concentrated depositor base: VC-backed startups who communicated in tight networks. Prominent VCs advised portfolio companies to withdraw funds. Depositors attempted to withdraw $42 billion in a single day. SVB was seized by the FDIC on March 10, 2023 — the second-largest US bank failure in history. The federal government backstopped all deposits above the $250,000 FDIC limit to prevent contagion across the startup ecosystem.

## Root Cause

SVB's collapse was a textbook duration mismatch: short-term liabilities (deposits that could be withdrawn immediately) funding long-term assets (bonds that would not mature for a decade). The bank accepted a decade of interest rate risk for a small yield pickup, without hedging. The problem was exacerbated by depositor concentration: unlike a retail bank with millions of small depositors who act independently, SVB's depositors were a tightly networked community that could coordinate a run in hours via group chats. SVB's risk management function did not flag either the rate exposure or the network contagion risk as existential.

## Key Decision Failures

- **Duration mismatch accepted without hedging**: SVB's investment committee bought long-dated bonds at historically low rates without purchasing interest rate swaps to hedge the duration risk. This was a known risk management failure, not an unforeseeable shock.
- **Depositor concentration not modeled as systemic risk**: SVB's depositor base was disproportionately VC-backed startups — a community that communicates rapidly and acts in coordination. Standard bank run models assume depositors act independently; SVB's did not.
- **Capital raise announcement poorly managed**: The decision to announce a loss-crystallizing securities sale simultaneously with a capital raise confirmed market fears and triggered the run it was meant to prevent. Execution sequencing was not managed.
- **Chief Risk Officer vacancy**: SVB had no permanent Chief Risk Officer for eight months preceding the collapse. The CRO role was filled by an interim officer during the period when rate exposure was building.

## Lessons

1. **Duration mismatch is a survival risk, not just a P&L risk**: A bank that funds long-duration assets with short-duration liabilities is solvent until it isn't — the transition is not gradual. Every CFO and treasurer must know the duration gap of their balance sheet and the scenario in which it becomes fatal.
2. **Concentrated stakeholders amplify every risk**: When your investors, customers, and creditors are the same networked community, a confidence shock propagates faster than any institution can respond. Concentration risk compounds all other risks.
3. **Risk function vacancies signal cultural de-prioritization**: An eight-month CRO vacancy at a bank with a rapidly growing balance sheet is not a hiring delay — it is a signal about what the institution believes the risk function is for.
