---
name: quarterly-forecast
description: Build a 4-quarter cash flow forecast from current burn, pipeline, and headcount plan
when_to_use: User asks for a cash forecast, runway projection, quarterly financial plan, or "are we going to run out of money"
category: finance
---

# Quarterly Cash Flow Forecast

## Inputs to gather first

Before building anything, confirm or ask for:

1. **Current cash position** — bank balance + receivables expected within 30 days
2. **Current monthly burn** — last 3 months net cash outflow, averaged
3. **Headcount plan** — hires planned by quarter, with target start dates and fully-loaded comp
4. **Revenue model** — for each revenue line: current ARR, contracted growth, pipeline-weighted forecast
5. **Known one-time items** — annual renewals, tax payments, hardware, marketing campaigns

If any of these is missing, stop and ask. A forecast built on guesses is worse than no forecast.

## Output structure

Produce a 4-quarter table with these rows, in this order:

| Row | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| Starting cash | | | | |
| Revenue (committed) | | | | |
| Revenue (pipeline-weighted, 40% factor) | | | | |
| Total cash in | | | | |
| Payroll (current team) | | | | |
| Payroll (new hires) | | | | |
| Non-payroll opex | | | | |
| One-time items | | | | |
| Total cash out | | | | |
| Net change | | | | |
| Ending cash | | | | |
| Runway (months) | | | | |

## Three scenarios

Always produce three scenarios in parallel:

- **Base case**: 40% pipeline conversion, hires happen on time, no churn surprises
- **Downside**: 20% pipeline conversion, hires slip 1 quarter, 10% gross-revenue churn surge
- **Upside**: 60% pipeline conversion, one accelerated logo lands a quarter early

## Closing summary

End with three sentences:
1. Months of runway in the base case at end of period
2. The single biggest swing factor between downside and base
3. One concrete decision the leadership should make in the next 30 days based on this forecast (raise timing, hire pause, expense action, pricing test)

Do not include disclaimers or hedge language. This is an operating tool, not a model.
