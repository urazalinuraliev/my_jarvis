# Product Analytics

Product analytics is how you replace opinion with evidence. The aim is not dashboards — it's better decisions. Most companies are over-instrumented (events everywhere) and under-analyzed (no one asks the questions the data could answer).

## The Metrics Hierarchy

Every product has metrics at three altitudes:

**1. North Star Metric (NSM)** — the single number representing customer value delivered
- Examples: Nights Booked (Airbnb), Time Spent Listening (Spotify), Daily Active Teams (Slack)
- See `product_strategy.md` for details

**2. Input Metrics** — the small set of behaviors that drive the NSM
- For Slack: messages sent, channels active, integrations connected
- For e-commerce: traffic, conversion rate, average order value, repeat purchase rate
- Usually 3-5 inputs per NSM

**3. Feature / Funnel Metrics** — granular behaviors specific to features or workflows
- Activation funnel conversion rates
- Feature adoption percentages
- Time-in-task, error rates, abandonment

When everything is reported up to leadership, focus on NSM and inputs. Feature metrics belong with the team that owns the feature.

## The Pirate Funnel (AARRR — Dave McClure)

A classic framework for SaaS / consumer product metrics:

- **Acquisition** — first visit / sign-up
- **Activation** — first valuable experience
- **Retention** — coming back over time
- **Revenue** — paying for value
- **Referral** — bringing in new users

**Modern adjustments:**
- Most companies should reorder to **Acquisition → Activation → Retention → Revenue → Referral** (AARRR) — historically McClure's order, sometimes scrambled
- Some add **Referral / Resurrection** for re-engaging churned users
- B2B SaaS often substitutes: **Lead → Trial → Activation → Conversion → Expansion → Retention**

The point: track conversion at each stage, find the biggest leak, fix that leak before optimizing elsewhere.

## Activation — The Underappreciated Metric

Activation = the user reaches the "aha moment" where they understand the value.

**Why it matters:**
- Activated users retain at 3-10x the rate of non-activated users
- Most signup-to-paid conversion failures are activation failures, not pricing failures
- Activation is fixable — once you know what causes it

**Finding your aha moment:**
- Look at retained users 30+ days in. What did they do in the first 7 days?
- Compare to churned users. What did the retained users do that the churned ones didn't?
- The behavioral difference often centers on a single action: "Added a teammate" (Slack), "Followed 10 users" (Twitter early days), "Connected an integration" (Zapier)

**Aha-moment patterns:**
- Slack: 2,000 messages sent in a workspace
- Facebook: 7 friends in 10 days
- Dropbox: 1 file in 1 folder on 1 device

These are not goals you set arbitrarily — they're statistical observations of what predicts retention. Find yours.

**The activation roadmap:**
- Instrument the funnel from signup to aha moment
- Identify the step with the biggest drop-off
- Run experiments to improve that step
- Repeat

This single discipline often produces more growth than any feature launch.

## Retention — The Most Important Metric

If acquisition is the front door, retention is the floor. A leaky retention curve cannot be patched by acquisition spend.

**Retention curve shapes (Sequoia/Bain framework):**

- **Smiling curve** — drops initially, then stabilizes flat (or even rises with engagement deepening). Indicates strong PMF.
- **Decay curve** — continuous decline, asymptotic to zero. Indicates weak PMF; users churning continuously.
- **Drop and flat** — high initial drop, stable thereafter. Indicates fit with a subset of users; investigate who stays.

Plot your retention as N-day curves (day 1, 7, 14, 30, 60, 90 retention). Compare cohorts over time — is it improving?

**Cohort analysis:**
- Group users by signup week/month
- Track retention of each cohort over time
- Reveals whether retention is improving or degrading as you grow

**Common retention diagnostics:**
- Cohort retention degrading with growth: you're acquiring lower-quality users (broader top-of-funnel; weaker positioning; cheaper paid channels)
- Cohort retention improving: product is finding fit; growth investment is paying off
- Cohort retention flat: status quo; usually a sign you're not running enough experiments

## Engagement Metrics

Within retained users, how deeply are they using the product?

**DAU/MAU (Daily Active Users / Monthly Active Users):**
- A stickiness measure
- 20-30%+ is high engagement (typical for tools)
- 50%+ is extraordinary (Facebook, WhatsApp)
- Below 10% may mean periodic-use product (Airbnb), not a problem

**WAU/MAU:**
- Often a better metric than DAU/MAU for B2B
- Most B2B products are not used daily by every user
- 50-70%+ WAU/MAU is healthy for typical SaaS

**Power user curve:**
- Distribution of users by usage intensity
- Healthy: long tail of light users + sizable group of power users
- Sick: cliff after light users; no power user concentration

**Engagement depth:**
- # of features used per user
- # of integrations / connections
- Time-to-first-value, time-to-second-value
- Network density (for collab/social products)

The right engagement metric depends on your product. Pick 2-3 that genuinely predict retention or revenue.

## A/B Testing

Live product experimentation is the strongest signal for which changes actually help.

**Prerequisites:**
- Enough traffic for statistical significance (typically 1000+ users per variant per week minimum)
- Instrumentation of the outcome metric
- Discipline to ship the winner, not the favored option

**Common mistakes:**

1. **Stopping early** — peeking at results before you have power. Inflates false positives.
2. **Multiple metrics, no Bonferroni correction** — if you test 20 metrics, you'll find a "significant" one by chance
3. **Local optimization without context** — A/B tests are blind to long-term effects; a 5% short-term lift might damage retention
4. **Tests for trivial changes** — button color changes that have no real impact, prioritized because they're easy
5. **No hypothesis** — testing for the sake of testing; can't learn from results because there was no expectation

**Best practices:**
- One primary metric per experiment
- Define hypothesis and expected lift upfront
- Pre-commit to a sample size and end date
- Document and share results (negative results matter — they prevent re-running)

**When NOT to A/B test:**
- Radical product changes (a new feature can't be tested against "no feature" without a different experimental design)
- Small user bases (no power)
- Decisions that need to be made fast and have low reversal cost (just ship and watch)

## Qualitative + Quantitative Together

Numbers tell you WHAT. Qualitative tells you WHY.

- Drop-off in funnel? Watch session recordings to see what users do at that step
- Churn spiked? Run exit interviews to find the trigger
- New feature underused? Talk to users who haven't tried it to learn why
- Power user pattern? Interview the power users to understand their workflows

The pattern: anomaly in the data → qualitative investigation → hypothesis → quantitative test.

Companies that rely on one or the other miss half the picture.

## Common Analytics Anti-Patterns

**1. Vanity metrics**
- Total registered users (most are inactive)
- Total downloads
- Page views
- Without engagement / conversion context, these mislead

**2. Dashboards as deliverables**
- Building dashboards no one reads
- Each new dashboard is a "win" but no decision changes
- Cure: dashboards are tools for specific decisions; if no one uses one, kill it

**3. Data hoarding**
- Tracking 1000+ events with no clear purpose
- Analytics platform performance degrades; team can't find what matters
- Cure: instrument with intent; review event taxonomy semi-annually

**4. Single-metric tyranny**
- One metric becomes the only thing that matters
- Team optimizes that metric while other things break
- Famous case: Facebook's MAU obsession leading to engagement-bait designs
- Cure: pair every primary metric with a guardrail metric (something that should NOT move adversely)

**5. Attribution as truth**
- "Marketing attribution shows that paid search drove 30% of revenue"
- Attribution is a model, not a measurement; treat as directional, not authoritative

## The Analytics Diagnostic

For your product, answer:
1. What's our North Star Metric? Is it customer-value oriented?
2. What 3-5 inputs drive the NSM?
3. What's our aha moment, and how many users reach it within 7 days?
4. What's our 30-day retention by cohort, and is it improving?
5. What was the last decision we changed because of data?

If you can't answer #5, your analytics setup is decorative.
