---
name: feature-prioritization
description: Apply a structured prioritization (RICE or similar) to a list of candidate features and produce a defensible ranking
when_to_use: User asks to prioritize a backlog, decide what to build next, or evaluate competing feature requests
category: product
---

# Feature Prioritization

A prioritization exercise produces a defensible ranking, not a single answer. The output should let the team explain WHY each item is where it is.

## Inputs to gather first

Before scoring anything, confirm or ask for:

1. **The list of candidate features** — minimum 3, ideally 8-15. Below 3 isn't a prioritization, it's a choice. Above 20, force a pre-cut.
2. **The strategic context** — what's the team's current outcome / OKR / North Star metric. Items that don't connect to this should be flagged.
3. **The customer segment being prioritized for** — different segments value different things; "for all customers" is rarely a useful target
4. **The team's capacity** — engineering-weeks available for this cycle. Determines how many items can actually be built.

If any of these is missing, stop and ask. Scoring without strategic context produces a mathematically clean answer to the wrong question.

## Method — RICE (default)

For each feature, score:

- **Reach** — how many customers/users affected per quarter (estimate)
- **Impact** — how much it affects each one
  - Massive: 3
  - High: 2
  - Medium: 1
  - Low: 0.5
  - Minimal: 0.25
- **Confidence** — how sure are you the numbers above are right
  - High: 1.0
  - Medium: 0.8
  - Low: 0.5
- **Effort** — engineering-weeks to build and ship

```
RICE Score = (Reach × Impact × Confidence) / Effort
```

If the team isn't comfortable with RICE, you can substitute ICE (Impact × Confidence × Ease), but RICE forces the Reach question, which is usually the underbaked one.

## Output structure

Produce three things:

### 1. Scoring table

| Feature | Reach | Impact | Conf | Effort | Score | Strategic fit |
|---|---|---|---|---|---|---|
| Feature A | 500 | 2 | 0.8 | 4 | 200 | ✓ Activation OKR |
| Feature B | 100 | 3 | 0.5 | 2 | 75 | ✓ Enterprise wedge |
| Feature C | 2000 | 1 | 1.0 | 8 | 250 | — Tangential |

Sort by score descending. Include "Strategic fit" column to surface where the math conflicts with strategy.

### 2. Ranked recommendation with rationale

Take the top items by score, BUT explicitly call out:

- Items where score and strategic fit diverge — recommend including a strategic-fit item even if it ranks lower, with rationale
- Items where Confidence is Low — these are bets, not commitments; flag as needing discovery work first
- Items with hidden dependencies that the team didn't include in Effort
- Items that look great but solve for the wrong segment

### 3. Explicit no-build list

The 3-5 highest-scoring items that you recommend NOT building this cycle, with the reason for each.

Reasons to defer:
- Strategy mismatch (it would move metrics, but not the metrics we care about right now)
- Confidence too low (needs discovery first)
- Capacity constraint (would crowd out higher-priority work)
- Dependency on a future capability not yet built

This list is the most important output. Anyone can pick a top 5. The discipline is being explicit about what you said no to and why.

## Discipline

- Show the math — if challenged on any score, you should be able to explain the input
- Be honest about Confidence — overstating it is the most common manipulation. If you're guessing, mark Low.
- Sales-pushed features get the same scoring as everything else — no priority for "the rep said the customer needs it" without evidence of impact and reach
- Recommend, don't decide — the PM (or product leader) makes the call; this analysis informs them

## What NOT to include

- A single number that "decides" — the framework informs judgment, doesn't replace it
- Generic feature descriptions — every feature needs enough description that scoring assumptions are testable
- Effort estimates without engineering input — PMs alone systematically under-estimate effort
- Items framed as solutions ("redesign onboarding") — re-frame as outcomes ("reduce time-to-activation from 14 to 7 days") and let solutions compete
