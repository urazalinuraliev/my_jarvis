# AI and Automation in the Enterprise

Every company is now an AI company whether or not they've decided to be. The decisions made in the next 12-24 months — which workflows to automate, which models to trust with which data, how to govern AI output — will compound in ways that are hard to reverse. The executives who move deliberately outperform both those who move recklessly and those who wait.

## The Adoption Frame

AI creates value through three distinct mechanisms:

**1. Augmentation** — humans do the same work faster and better (drafting, synthesis, research, code review)

**2. Automation** — humans hand off a workflow entirely (document processing, ticket routing, data transformation, first-line support)

**3. Net-new capability** — things previously impossible at the company's scale become feasible (personalization at scale, 24/7 multilingual support, real-time pattern detection across large datasets)

Most early enterprise AI value is augmentation. Automation and net-new capability require more process redesign and governance investment. Sequencing matters: build capability and trust with augmentation before automating high-stakes decisions.

## Where AI Creates the Most Executive Leverage

**Finance:**
- FP&A: automated variance analysis, scenario generation, board commentary drafting
- Accounts payable: invoice processing, duplicate detection, three-way match
- Forecasting: model refresh and anomaly flagging without analyst bottleneck

**Sales and Marketing:**
- Lead scoring and prioritization
- Personalized outreach at scale
- Call summarization and CRM population
- Competitive intelligence synthesis

**Product and Engineering:**
- Code generation, review, and documentation (GitHub Copilot, Cursor, etc.)
- Bug triage and root cause analysis
- User research synthesis (interview → themes → insights)

**HR:**
- Resume screening and initial qualification
- Onboarding content generation and Q&A
- People analytics and attrition prediction

**Customer Support:**
- Tier-1 deflection (FAQ, status, common workflows)
- Agent assist (suggested responses, knowledge surfacing)
- CSAT prediction and escalation routing

**Legal and Compliance:**
- Contract review and redlining for standard terms
- Regulatory change monitoring and gap analysis
- Policy document generation from templates

## The Governance Imperative

AI moves fast enough that governance often lags by 18+ months. The gap creates liability.

**Minimum viable AI governance (any company):**
- *Approved tool list*: which AI tools employees may use, for what, with what data
- *Data classification applied to AI*: which data can flow into which models (public, internal, confidential, regulated)
- *Output review policy*: which AI outputs require human review before action (legal filings, financial statements, customer communications, medical advice — never autonomous)
- *Vendor risk review*: AI vendors assessed for data handling, model training practices, breach protocols

**The most common failure mode:**
- Employees use consumer AI tools (ChatGPT, Claude.ai, Gemini) for work
- Confidential data, customer PII, code, financial projections flow into models
- Vendor trains on this data or experiences a breach
- Company discovers this during a security review or incident — not before

**Cure:** Default-allow creates this problem. Default-deny with an approved list is operationally harder initially but avoids categorical risk.

## Evaluating AI Vendors

Questions to ask before signing:

**Data and training:**
- Does using the API train the model on our inputs by default? What opt-out exists?
- Where is data processed and stored? In which jurisdictions?
- What is the data retention and deletion policy?

**Model behavior and reliability:**
- What accuracy benchmarks exist for our use case?
- What hallucination rate and citation verification capability?
- What monitoring and alerting exist for model drift?

**Commercial and operational:**
- What are the rate limits and SLAs?
- What happens to our outputs and fine-tuned models if we terminate?
- What is the liability posture for AI errors that cause downstream harm?

## Build vs. Buy vs. API

**Build (custom model training/fine-tuning):**
- Justified for: unique proprietary data, extreme quality bar, competitive differentiation
- Not justified for: general productivity, commodity tasks, limited AI team
- Cost is higher than commonly estimated: training, serving infrastructure, evals, ongoing maintenance

**API (prompt-based, frontier models):**
- Right for: most enterprise use cases, speed to value, capability breadth
- Key providers: Anthropic (Claude), OpenAI (GPT), Google (Gemini), AWS (Bedrock)
- Prompt caching, structured outputs, and tool use are the mechanisms that unlock reliable enterprise behavior

**Buy (SaaS products with embedded AI):**
- Fastest time-to-value for defined workflows
- Vendor controls model choice and update cadence — evaluate their governance practices, not just the UX

Most companies should default to API or buy; build only when a clear strategic case exists.

## Measuring AI ROI

AI investments are often under-measured.

**Time savings metrics:**
- Hours saved per week per user × loaded hourly cost × headcount
- Task completion time before vs. after (track, don't estimate)
- Error rate and rework reduction

**Quality metrics:**
- Customer satisfaction delta for AI-assisted vs. human-only interactions
- Code defect rate before/after AI-assisted review
- Document accuracy or compliance error rate

**Capability metrics:**
- Volume of tasks completed that were previously un-done (backlog cleared)
- New product or feature capabilities unlocked
- Customer or market opportunities newly addressable

**Vanity metrics to avoid:**
- "Number of AI tools deployed" — proliferation ≠ impact
- "Employees trained on AI" — usage and value realized matter, not training completion

## Change Management for AI Adoption

The technology is rarely the hard part.

**Fear and resistance:**
- Employees fear job displacement — often outstrips actual automation risk
- Address directly: be honest about what will change; be specific about what won't
- The most effective communicators frame AI as "I want you doing the interesting work, not the repetitive work"

**Trust calibration:**
- Users initially over-trust AI output (accept without review) or under-trust (revert to manual process)
- Both are problems — calibrated trust requires seeing where AI fails as well as where it succeeds
- Structured pilots with explicit success/failure tracking calibrate this better than general rollouts

**Incentives:**
- If employees are measured on output volume, AI that increases output benefits them
- If they're measured on expertise that AI partially replicates, they have no incentive to adopt
- Review how AI interacts with existing incentive structures before rollout

## The Executive Decision Framework

For any proposed AI initiative, answer:
1. **What human work is this replacing or augmenting?** (If you can't answer, the use case is too vague)
2. **What's the error cost?** (AI errors in low-stakes contexts are fine; in high-stakes contexts, require human review)
3. **What data is required, and is it permissible to use?** (Data classification gate)
4. **What does good look like, and how will we measure it?** (Baseline before deploying)
5. **What's the fallback if the model fails or degrades?** (Always have one)

Companies that answer these before deploying avoid most of the predictable failures. Companies that skip them discover the answers expensively.
