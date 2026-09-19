# Experimentation — A/B Testing and Feature Rollouts

Experimentation is how product decisions stop being arguments and become evidence. Companies with strong experimentation cultures make more decisions, make them faster, and make them more accurately. Companies without them rely on the highest-paid person's opinion (HiPPO), which is slower and wrong more often.

## What Experimentation Actually Is

An experiment is a controlled comparison: one group of users gets treatment A, another gets treatment B, and you measure a defined outcome for both. The randomization is what makes the comparison valid — it controls for confounding variables.

**The bar for an experiment:**
- Random assignment (not sequential, not geographic unless geo-experiment)
- Adequate sample size (determined by power analysis before the experiment starts)
- Pre-specified primary metric (set before you see results)
- Minimum detectable effect defined upfront (what change is worth detecting?)

Without these, you have an observation, not an experiment. Observations are fine — they generate hypotheses. Experiments validate them.

## The Experimentation Infrastructure Stack

**Experiment assignment:** The system that determines which variant each user sees. Must be deterministic per user (same user always sees same variant) and random across users.

**Feature flags:** The mechanism that shows variant behavior to the right users. Decouples deployment from release — code ships to production, but only some users see it.

**Event tracking:** User actions logged with experiment assignment. You can't measure what you don't track. Define tracking requirements before shipping, not after.

**Metrics platform:** Aggregates events into experiment metrics, runs statistical tests, and surfaces results. Tools: Statsig, Amplitude Experiment, Optimizely, LaunchDarkly with external analytics, or homegrown.

**Results interface:** Where teams see experiment outcomes, drill into segments, and make ship/kill decisions.

## Statistical Foundations — What You Need to Know

**P-value:** The probability of observing this result (or more extreme) if there were no real difference. P < 0.05 means less than 5% chance the result is due to random variation alone. Not the probability that your hypothesis is true.

**Statistical significance:** Conventionally p < 0.05. This is a threshold, not a guarantee. 1 in 20 significant results is a false positive at this threshold by definition.

**Statistical power:** The probability of detecting a real effect when one exists. Standard target: 80%. Below 80% power, you'll miss real improvements frequently.

**Sample size and duration:**
- Smaller effects require larger samples to detect reliably
- Use a sample size calculator (Evan Miller's, Statsig's, or your platform's) before launching
- Minimum experiment duration is usually 1-2 full business weeks (captures weekly cycles)
- Don't stop early because results look good — p-value hacking inflates false positives

**Confidence interval:** The range of values compatible with your data. A 95% CI of [+2%, +8%] on conversion rate says the true effect is probably in that range. Width of CI tells you precision.

**Sequential testing / always-valid p-values:** Modern platforms (Statsig, Optimizely) use sequential testing that lets you peek at results without inflating false positives. This is the right approach for continuous deployment environments; traditional fixed-horizon testing is not.

## Metric Selection

The most important decision you make before running an experiment.

**Primary metric:** The one metric that decides ship/kill. One, not three. If it improves, you ship regardless of other metrics. Choose it based on what the experiment is actually trying to improve, not what will make it look good.

**Guardrail metrics:** Metrics that must not degrade. Even if primary metric improves, you don't ship if a guardrail breaks. Typical guardrails: latency, error rate, revenue per user, core retention.

**Secondary metrics:** Directional signals that help interpret why the primary metric moved. Not decision-makers.

**North Star vs. proxy metrics:**
- North Star (e.g., weekly active users, revenue): the real thing; slow to move; not useful for individual experiments
- Proxy metrics (e.g., activation rate, D7 retention): correlated with North Star; faster to detect; acceptable for experiments if the correlation is validated

**Metric sensitivity:**
- Some metrics are inherently noisy (revenue per user has high variance; outliers dominate)
- Some metrics are low-frequency (conversion from trial to paid happens rarely; requires huge sample)
- Match metric to the expected effect size and your traffic volume

## Common Experiment Types

**UI/UX experiments:** Button copy, layout, onboarding flow, navigation. High sensitivity; usually measurable in days.

**Algorithm experiments:** Ranking, recommendation, search, pricing. Often the highest business impact. Requires careful metric design (engagement vs. revenue vs. long-term satisfaction).

**New feature experiments:** Ship a feature to 50% of users, measure impact on target metric. Gate full release on result.

**Holdout experiments:** Keep a group of users in "old experience" while everyone else gets new changes. Measures cumulative impact of multiple changes over time. Important for detecting cannibalization or interaction effects.

**Geo experiments:** Used when randomization at user level is impossible (marketplace dynamics, pricing, TV campaigns). Compare outcomes in treatment vs. control geographies.

## Running Experiments Well

**Before launch:**
- Define hypothesis: "We believe [change] will improve [metric] by [magnitude] because [reasoning]"
- Calculate required sample size
- Confirm event tracking is live and correct
- Set analysis date (when you'll look at results)
- Align stakeholders on decision criteria: "We'll ship if primary metric is +X% significant"

**During the experiment:**
- Monitor health checks: is assignment balanced? Is tracking firing? Any bugs in the treatment?
- Resist peeking at outcome metrics — sequential testing handles this if your platform supports it; traditional fixed-horizon tests don't
- If something is clearly broken (major regression, bug), stop early; otherwise don't

**At analysis:**
- Primary metric result + confidence interval
- Guardrail check
- Segment analysis (mobile vs. desktop, new vs. returning, by plan tier) — often reveals heterogeneous effects
- Ship/kill/iterate decision with documented rationale

**After the experiment:**
- Write it up: hypothesis, result, interpretation, decision. Even a short doc. Future teams need this.
- Update the experiment log or registry

## Feature Flags as Release Mechanism

Modern feature flags decouple deployment from release. Benefits:

**Gradual rollout (canary release):**
- Ship to 1% → 10% → 50% → 100%
- Monitor metrics at each step before expanding
- Instant kill-switch if something breaks

**Kill switch:**
- Feature in production behind a flag
- If post-launch monitoring shows regression, disable instantly without a deploy
- Essential for high-risk changes

**Targeted access:**
- Show feature to beta customers, internal users, or specific cohorts before wide release
- Used for early access programs, dogfooding, enterprise-specific features

**A/B testing integration:**
- Flag values can be assigned randomly for experiments
- Experiment infrastructure and feature flag infrastructure often converge

Tools: LaunchDarkly, Statsig, Split.io, Unleash (open source), Flipt (open source), or rolled-in-house.

## Organizational Culture of Experimentation

Infrastructure is the easy part. Culture is harder.

**Prerequisites for a strong experiment culture:**
- *Speed of iteration* — experiments only create value if teams can run many. If each experiment takes 6 weeks to define, instrument, and analyze, you'll run 8 a year. Industry leaders run hundreds.
- *Tolerance for null results* — most experiments don't show improvement. This is information, not failure. Teams that are punished for null results stop running experiments.
- *Separation of experimentation from feature delivery* — if "shipped" means "shipped to 100% without validation," you've removed the feedback loop
- *Metrics ownership* — teams that own outcomes (not just outputs) want experiments; teams measured by features shipped want to skip validation

**Leading indicators of a healthy culture:**
- Experiment win rate 20-40% (if >50%, you're not testing risky-enough ideas; if <10%, either ideas are weak or execution is broken)
- Results documented in a searchable registry
- New engineers onboarded to experiment platform in first week
- PM job descriptions include "data-informed" and evaluate past experiment velocity

## What Experiments Can't Tell You

- **Long-term effects:** A 2-week experiment on onboarding can't tell you about 6-month retention
- **Strategic direction:** Experiments answer "is A better than B?" not "should we be doing A or B at all?"
- **Novel features:** If users have never seen something, they often react poorly initially (novelty effect); retention experiments are more reliable than conversion experiments for genuinely new concepts
- **Small-traffic scenarios:** Low-traffic pages, niche user segments, infrequent events — may never reach significance; use qualitative methods instead

Experimentation is one tool in the product decision toolkit. Qualitative research, competitor analysis, customer interviews, and strategic judgment are the others. Strong product organizations use all of them, appropriately.
