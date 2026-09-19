# Product Discovery

Product discovery is the work of figuring out what to build before you build it. The reason most products fail is not that they were built badly — it's that they were the wrong things to build. Discovery is the cheapest insurance against that failure.

## The Two Tracks

**Discovery** — answers "is this worth building? what should we build?"

**Delivery** — answers "build it and ship it."

Mature product teams run both in parallel ("dual-track agile" — Marty Cagan, Jeff Patton). Discovery 6-12 weeks ahead of delivery. The output of discovery feeds delivery; the output of delivery feeds new discovery questions.

Teams that run only delivery ship more bad features faster.

## Four Risks Discovery Must Address

Marty Cagan's framework — any product effort must answer four questions:

1. **Value risk** — will the customer choose to use this?
2. **Usability risk** — can they figure out how to use it?
3. **Feasibility risk** — can we actually build it?
4. **Business viability risk** — does this work for our business (legal, financial, brand, channel)?

Different roles own each:
- Value: product manager (with research and design input)
- Usability: design
- Feasibility: engineering
- Viability: product manager (with legal, finance, marketing input)

Skipping any of the four creates the gap that makes the product fail post-launch.

## Customer Interviews — The Highest-Leverage Discovery Activity

Customer interviews are dirt-cheap, high-information, and almost universally underused. A weekly cadence of 3-5 interviews is the default discipline of strong product teams.

**Who to interview:**
- Target customers (haven't bought, fit the ICP)
- Recent buyers (just chose you — why?)
- Recent losses (chose a competitor or status quo — why?)
- Churned customers (left — why?)
- Power users (use you a lot — what for?)

**What to ask (problem interviews):**
- Walk me through the last time you [did the job]. What did you do, step by step?
- What was hard or frustrating about that?
- How did you ultimately get it done?
- What did you try that didn't work?
- If a magic wand could fix one thing about that experience, what?

**What NOT to ask:**
- "Would you use a product that does X?" (Customers say yes to everything in hypotheticals; useless data)
- "How much would you pay for X?" (Same — useless without real intent)
- "What features would you want?" (Customers describe solutions; you need problems)

**Discipline:**
- Open-ended questions, not yes/no
- Past behavior, not future intent
- Specific examples, not generalizations
- 60 minutes max — declining returns after that

**The Mom Test (Rob Fitzpatrick) — three rules:**
1. Talk about their life, not your idea
2. Ask about specifics in the past, not opinions about the future
3. Talk less, listen more

## Jobs-to-be-Done (JTBD) Interviews

A specific interview methodology focused on uncovering the "switch" — the moment a customer decided to change from one solution to another.

**The switch interview structure:**
- Start with the moment they decided to switch (or buy your product)
- Walk backward: what triggered the search? What were the alternatives? What pushed them toward your solution? What pulled them away from the old solution?
- Walk forward: what was the experience after switching? What was better? What was worse?

**Four forces of progress:**
1. **Push** of the current situation (what's bad about today)
2. **Pull** of the new solution (what's attractive about the alternative)
3. **Anxiety** about switching (fears about the new solution)
4. **Habit** of the present (inertia toward what they already use)

Push + Pull > Anxiety + Habit = switch happens.

If you can articulate these four forces for your buyers, you understand your customer better than 90% of your competitors.

## Opportunity-Solution Tree (Teresa Torres)

A visual structure for connecting customer opportunities to product solutions, used throughout discovery.

```
                    Outcome (business goal)
                            |
        ___________________________________________
       |              |              |             |
   Opportunity 1   Opportunity 2  Opportunity 3   ...
       |
    ___________
   |     |     |
 Sol 1  Sol 2 Sol 3
   |
 Experiment 1
```

**Mechanics:**
- Top: the outcome you're trying to drive (e.g., "increase activation rate")
- Layer 2: opportunities (customer needs or pain points that, if addressed, would drive the outcome)
- Layer 3: solutions (potential ways to address each opportunity)
- Layer 4: experiments (cheap tests to validate solutions before fully building)

**Why it works:**
- Forces explicit connection between solution and outcome
- Multiple solutions per opportunity prevents premature solution lock-in
- Multiple opportunities prevents premature opportunity lock-in
- Living document — updated as you learn

## Discovery Methods Beyond Interviews

**Concept testing:**
- Show mockups or prototypes to target customers, gather reactions
- Watch their body language, not just listen to words
- Useful for usability and emotional reaction
- Watch out: customers are polite; reactions skew positive

**Wizard of Oz prototypes:**
- Build a real-feeling experience powered by humans behind the scenes
- Tests demand and value without engineering investment
- Famous example: Aardvark (Q&A service that was humans relaying questions before scaled tech)

**Smoke tests:**
- Build a landing page for a not-yet-existing product
- Measure signup intent
- Often used pre-launch to validate demand
- Caveat: signup intent ≠ paying intent

**Painted door tests:**
- Add a feature entry-point in an existing product (button, link)
- Click leads to "coming soon" page that captures interest
- Measures interest without building the feature
- Risk: confusing or frustrating users who clicked expecting it to work

**A/B tests:**
- Real product changes shown to subsets of users
- Best signal possible: behavioral, not stated
- Limited to incremental changes (radical new features can't be A/B tested cleanly)

**Customer advisory boards:**
- 6-15 customers, quarterly conversations on strategic direction
- Not for tactical feedback (interviews are better)
- For: strategic validation, executive engagement, product-led references

## Common Discovery Anti-Patterns

**1. The "we know what to build" trap**
- Skipping discovery because the team feels confident
- Resulting features ship to lukewarm reception
- Cure: even confident teams should run 2-3 interviews to test assumptions

**2. Build, then research**
- Validating after shipping ("did people like it?")
- Sunk cost makes it hard to act on negative findings
- Cure: discovery before delivery, not after

**3. Demoware**
- Building polished features for executive demos, not for actual users
- Demos go well, real users don't adopt
- Cure: instrumentation of real usage, not demo plays

**4. Outsourcing discovery to a research team**
- Researchers do interviews, write reports, hand to PMs
- PMs don't internalize, build different things
- Cure: PMs in interviews, side-by-side with researchers

**5. Treating sales as discovery**
- Sales reps demand features for deals; treating each request as a discovery signal
- Roadmap becomes a deal log
- Cure: discovery is its own activity, separate from sales escalations (though sales is one input)

## Discovery Cadence

**Weekly:**
- 3-5 customer interviews (problem, switch, or concept)
- Synthesis (what we heard, what we're updating)

**Monthly:**
- Opportunity-Solution Tree review and update
- Experiment results review

**Quarterly:**
- Major discovery research (deep customer cohort study, strategic validation)
- Strategy review informed by discovery learnings

## The Discovery Diagnostic

For any feature on the roadmap, ask:
1. What customer problem does this solve? In whose words?
2. How many interviews have we done to validate this?
3. What's our riskiest assumption — and how will we test it before building?
4. What does success look like? (User behavior, not feature shipped)
5. What would tell us this isn't the right thing?

If the answers to 1, 2, 3, 5 are weak, you're heading into delivery with discovery debt. Pay it down before you ship.
