# Product-Led Growth

Product-Led Growth (PLG) is a go-to-market strategy where the product itself drives user acquisition, conversion, and expansion. Users find, adopt, expand, and refer the product with minimal sales involvement. Done right, PLG produces extraordinary capital efficiency. Done badly, it's a free trial bolted onto a sales-led business that converts no one.

## What PLG Actually Requires

PLG is not "we have a free trial." Real PLG requires:

1. **A product that delivers value in minutes, not weeks** — fast time-to-value
2. **Self-service onboarding** — no human required to get a user to the aha moment
3. **In-product growth triggers** — usage-based prompts to invite, share, upgrade
4. **Pricing aligned with usage** — value-based, expansion-friendly
5. **Data-driven product team** — every interaction instrumented and analyzed

The companies that make PLG work invest heavily in these. The ones that fail at PLG missed one or more.

**Iconic PLG examples:**
- Slack (free workspace; pay when team grows)
- Figma (free for individuals; pay for teams and orgs)
- Notion (free for personal; pay for collaboration)
- Calendly (free for basic; pay for advanced features)
- Loom (free recording; pay for storage and admin)
- Linear (free for small teams; pay for org features)

These are not "freemium with a sales team." They're products designed top-to-bottom for self-service.

## The PLG Funnel

The funnel looks different from sales-led:

```
Visit
  → Sign up (free)
    → Activated (reached aha moment)
      → Habit (repeated use)
        → Convert to paid (individual or team)
          → Expand (more seats, higher tier)
            → Refer (bring colleagues)
```

**Conversion benchmarks (B2B SaaS PLG):**
- Visit → Sign up: 1-3%
- Sign up → Activated: 20-40% (varies hugely by product)
- Activated → Habit (return regularly): 40-60%
- Free → Paid: 2-5% over 12 months (good); 8-15% (excellent)
- Paid expansion: 15-30% annual (good); 30-50% (excellent)
- Referral coefficient: varies hugely; 0.5+ is strong organic growth

Each stage of the funnel is its own optimization problem.

## Time-to-Value (TTV)

The single most important PLG metric. How long from signup to "the user has gotten value"?

**Examples:**
- Calendly: minutes (set up your calendar, share a link, get a meeting booked)
- Loom: minutes (record a video, share it)
- Notion: hours-to-days (build your first useful workspace)
- Salesforce: weeks-to-months (NOT a PLG fit)

**The TTV improvement work:**
- Reduce onboarding friction (every required field is a tax)
- Pre-populate or template common use cases
- Show value before requiring full setup (let users see what they'd get)
- Eliminate human dependencies (no "schedule a call to get access")

Companies obsessing over TTV often see 2-3x improvement in activation rate.

## The Aha Moment

The specific behavior that strongly predicts retention. (See `product_analytics.md`.)

**Identifying it:**
- Compare retained users at day 30 to churned users
- Find the action(s) where retained users diverged
- Common patterns: connecting an integration, inviting a teammate, completing first project, sending first transaction

**Examples:**
- Slack: 2,000 messages sent in a workspace
- Facebook: 7 friends in 10 days
- Dropbox: 1 file in 1 folder on 1 device
- Zoom: first scheduled meeting attended

**Designing for it:**
- Make the aha moment visible in onboarding
- Remove friction to reaching it
- Celebrate it when reached (in-product moment, email, confetti — something)
- Track reach rate as a primary metric

## Pricing for PLG

PLG pricing has unique requirements.

**Free tier design:**
- Must deliver real value (not "demo" or "trial")
- Must have natural limits that trigger upgrade (seats, usage, features, projects)
- Free tier becomes the marketing surface — invest in it

**Conversion triggers:**
- Per-seat: collaboration features locked behind paid
- Usage-based: capacity limits create natural upgrade pressure
- Feature-based: advanced features locked behind upgrade

**Pricing tiers:**
- Free: individual use, basic features
- Personal / Starter: $5-20/month, individual power users
- Team: $10-50/seat/month, small teams
- Business: $20-100/seat/month, larger teams with admin/integrations
- Enterprise: custom, large orgs with SSO/security/compliance

Match price to value perception, not cost-to-serve.

**The freemium math:**
- 100,000 free users × 2-5% conversion × $200/year = $400k-$1M ARR
- Same audience at sales-led would require 100x the sales team
- The economics work IF activation and conversion rates hold

## Land-and-Expand

The PLG expansion motion: get in cheap, grow within the account.

**The pattern:**
1. Individual or small team adopts free (or low-priced)
2. Use spreads organically within the company
3. Eventually hits limits (seats, usage, admin needs)
4. Upgrade to higher tier
5. Continued expansion to enterprise contract

**Expansion levers:**
- Per-seat growth (more users invited)
- Tier upgrades (advanced features needed)
- Usage growth (consumption-based)
- Premium features (admin, security, analytics)
- Adjacent products (suite expansion)

**The expansion infrastructure:**
- Usage analytics by account (know who's growing)
- In-product upgrade prompts (relevant, contextual)
- Lifecycle email and in-app messaging
- "Account-level" view of all users in a company
- Reach-out from sales when accounts hit thresholds (PLG + sales overlay)

## PLG + Sales: Not Either/Or

Pure PLG works for self-serve / SMB. For mid-market and enterprise, PLG + sales overlay is the dominant pattern.

**The PLG-led sales motion:**
- Marketing drives sign-ups
- Product drives activation and viral adoption within accounts
- Sales engages when accounts reach a threshold (multiple users, paid tier, usage spike)
- Sales focuses on: expansion to enterprise tier, multi-year contracts, security/admin needs

**Triggers for sales engagement:**
- N+ users from same domain
- Multiple paid seats in same account
- High usage trajectory
- Inquiries about SSO, SOC 2, custom contracts, volume discounts
- Inbound demo requests from titles indicating buying authority

**Why this works:**
- Product validates demand and shrinks sales cycle
- Sales doesn't waste time on accounts that won't convert
- Customer comes pre-educated (they've used the product)
- Sales focuses on bigger commercial terms, not basic education

## PLG Metrics Stack

**Acquisition:**
- Sign-ups per period
- Sign-up source mix
- Activation rate (sign-up → aha moment within N days)

**Engagement:**
- WAU/MAU or DAU/MAU
- Time to second / third action
- Feature adoption rates

**Retention:**
- Cohort retention curves (weekly, monthly)
- Free user retention vs. paid retention
- Churn reasons (surveyed at cancellation)

**Conversion:**
- Free-to-paid conversion (overall and by cohort)
- Time to conversion (median)
- Conversion by trigger (seat limit, feature gate, etc.)

**Expansion:**
- Net Revenue Retention (paid users)
- Expansion rate (% of customers expanding per period)
- Average expansion size

**Virality:**
- K-factor (new users per existing user per period)
- Invites sent per active user
- Invite conversion rate

These metrics inform a flywheel. Improving any one tends to improve others; degrading any one tends to degrade others.

## PLG Anti-Patterns

**1. PLG with sales-led product**
- Product requires onboarding meeting
- Configuration takes hours
- Free trial expires before value seen
- Conversion is dependent on sales rep, not product
- Cure: redesign the product for self-service or admit it's sales-led

**2. Free tier with no upgrade pressure**
- Generous free tier; no natural reason to upgrade
- Free users stay free forever
- Cure: design limits aligned with growth (more seats, more usage, more features)

**3. Sales team paid on PLG conversions**
- Sales comp incentivizes overriding product-led signals
- Reps push for sales-cycle-style deals
- Cure: separate PLG conversions (no rep involvement) from sales motion (rep involvement); compensate accordingly

**4. Adding sales-led process to working PLG**
- "Let's add SDR outreach to all signups"
- Friction added; conversion drops
- Cure: layer sales over PLG triggers, not replace PLG

**5. Insufficient instrumentation**
- Can't measure aha moment, activation, churn drivers
- Improvements are guesswork
- Cure: invest in product analytics infrastructure before scaling

## When NOT to Do PLG

PLG is wrong for:
- Products requiring extensive onboarding (Workday, SAP)
- Sales involving multiple stakeholders with custom RFPs
- Highly-regulated industries with procurement processes
- High-ACV deals (>$50k) where sales is required regardless
- Products that need significant configuration to deliver value

These are sales-led businesses. Trying to bolt PLG onto them creates a confused funnel that's slower than pure sales.

**Hybrid (PLG + sales-led overlay) works when:**
- Self-serve makes sense for SMB / individual users
- Enterprise sales motion exists for larger deals
- Triggers move accounts from one motion to the other

## The PLG Diagnostic

For your business, ask:
1. What's our time-to-value for the median new user?
2. What's our activation rate (signup → aha moment)?
3. What's our free-to-paid conversion in 12 months?
4. What's our K-factor (viral coefficient)?
5. If we removed all sales involvement, what % of revenue would we still get?

#5 is the honest PLG test. If the answer is <30%, PLG is supplementary at best. If the answer is >60%, PLG is the actual motion and the rest is overlay.
