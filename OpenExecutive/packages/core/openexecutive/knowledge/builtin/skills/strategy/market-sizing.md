---
name: market-sizing
description: Produce a defensible TAM/SAM/SOM analysis for a market or segment with bottoms-up math
when_to_use: User asks about market size, TAM, addressable market, opportunity sizing for a new market or vertical
category: strategy
---

# Market Sizing (TAM / SAM / SOM)

Market sizing is a forcing function for clear thinking about who you'd sell to, at what price, and what the realistic ceiling is. Done badly, it's a number plucked from a Gartner report. Done well, it's a defensible build-up the team can use to decide where to invest.

## Inputs to gather first

Before sizing anything, confirm or ask for:

1. **The market being sized** — be precise; "B2B SaaS" is not a market, "mid-market RevOps platforms for North American B2B SaaS companies" is
2. **The buyer / use case** — who specifically would buy, for what
3. **The price point or pricing model** — current pricing or assumed pricing
4. **The geographic scope** — global, US, North America, EMEA, etc.
5. **The customer segment** — SMB, mid-market, enterprise (with size definitions)

If any of these is missing, stop and ask. Vague inputs produce vague (and indefensible) outputs.

## The three layers

### TAM — Total Addressable Market

The total annual revenue opportunity if every potential buyer in your market bought your product at your price.

**Method 1: Top-down (industry data)**
- Start with an analyst report on the market size
- Adjust for your specific category definition
- Useful for sanity check; not enough on its own

**Method 2: Bottoms-up (number of buyers × ACV)**
- # of companies / users in target segment globally
- × % that fit your specific ICP
- × annual contract value (ACV) at your pricing
- = TAM

Bottoms-up is more defensible. Always do bottoms-up; use top-down as a check.

### SAM — Serviceable Addressable Market

The portion of TAM you can realistically address given language, geography, channel, regulation, integrations.

- TAM × (% addressable today given current product, languages, geos)
- Usually 20-50% of TAM for early companies; 60-90% for mature

### SOM — Serviceable Obtainable Market

The portion of SAM you can realistically capture in a defined time period (typically 3-5 years).

- SAM × realistic market share %
- For early markets: 1-5% over 3 years is realistic
- For established competitive markets: 5-20% over 3-5 years
- "We'll capture 50%" is almost never realistic

## Output structure

Produce three sections:

### Section 1: TAM build-up

A table or paragraph showing:
- Total population of potential buyers (companies, individuals, etc.) — with source
- % matching your ICP
- ACV assumption — with rationale
- TAM calculation

Example: "There are ~30,000 mid-market B2B SaaS companies in NA (Source: PitchBook). Of these, ~40% have $5M+ ARR (the threshold for needing a RevOps platform per customer interviews). At our pricing of $50k ACV, TAM = 30,000 × 40% × $50k = $600M."

### Section 2: SAM

What portion of TAM is reachable today, and why the rest isn't.

Example: "Of the $600M TAM, ~70% is in English-speaking markets where we currently sell. SOC 2 Type II requirement excludes ~10% of TAM in highly-regulated verticals. SAM = $600M × 60% = $360M."

### Section 3: SOM (3-year)

Realistic capture given competitive landscape, GTM capacity, product maturity.

Example: "Three direct competitors exist; we believe we can take 5-10% share over 3 years given current GTM investment. SOM (Year 3) = $360M × 7% = $25M ARR opportunity."

### Section 4: Sanity checks

For each layer:
- Does the # of buyers match other known data (e.g., LinkedIn search of target titles)?
- Does the ACV match what comparable companies are charging?
- Does the SOM share match the team's actual capacity to capture (sales reps × productivity × win rate)?

If any sanity check fails, revise the underlying numbers.

## Discipline

- **Show the math.** Every number traces to a source or explicit assumption.
- **Cite sources.** "Per industry analyst" is weak; "per PitchBook 2024 SaaS Funding Report" is defendable.
- **Be honest about assumptions.** If you guessed ACV, say so.
- **Distinguish addressable from obtainable.** TAM is a ceiling; SOM is realistic.
- **Time-bound the SOM.** "$50M opportunity" without a timeline is ambiguous.

## What NOT to include

- Single number with no build-up ("$10B TAM!")
- TAM defined as a broad category your product doesn't actually serve
- "Bottom-up" math that's actually a market share assumption disguised as a count
- 50%+ market share assumptions for SOM (almost always wrong)
- Numbers that don't pass sanity check against comparable companies' actual results

## Closing summary

End with three sentences:

1. The defensible TAM and SOM
2. The biggest assumption that, if wrong, would change the answer most
3. The implication for strategy: this is a market we should invest heavily in / partially in / not pursue
