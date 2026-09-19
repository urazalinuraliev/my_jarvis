# Project and Program Management

Projects fail less often because of bad people and more often because of bad structure. Most "execution problems" are problems of unclear ownership, scope creep, or a methodology mismatched to the work.

## Project Management Methodologies — Pick the Right One

**Waterfall** — sequential phases (requirements → design → build → test → deploy)
- *Right for*: well-understood requirements, fixed scope, regulated environments, hardware
- *Wrong for*: anything where requirements will change during build
- *Failure mode*: completing on time and budget, delivering the wrong thing

**Agile (umbrella term)** — iterative delivery with frequent customer feedback
- *Right for*: software, anywhere requirements are uncertain or will evolve
- *Wrong for*: hard external deadlines with no scope flexibility
- *Failure mode*: continuous iteration with no shipping, "agile theater" (rituals without principles)

**Scrum** — Agile variant with sprints (typically 2 weeks), defined roles (PO, Scrum Master, Dev Team), ceremonies (planning, daily standup, review, retro)
- *Right for*: cross-functional product teams shipping incrementally
- *Wrong for*: small teams where overhead exceeds benefit; ops teams with reactive workloads
- *Failure mode*: ritual without outcome; sprint completion becomes the metric

**Kanban** — continuous flow with WIP (work-in-progress) limits, visualized on a board
- *Right for*: operational teams with unpredictable, ad-hoc work (support, infra, security)
- *Wrong for*: large multi-team initiatives requiring coordination
- *Failure mode*: no urgency; work flows but nothing of note ships

**Shape Up** (Basecamp) — 6-week appetites with fixed time, variable scope
- *Right for*: small product teams shipping bets
- *Wrong for*: programs requiring coordination across many teams
- *Failure mode*: scope-cutting becomes scope-deletion of important work

The methodology is the wrapper. The principles matter more: customer-facing outcomes, frequent shipping, owned by named individuals, retrospectives that change behavior.

## The Triple Constraint (Iron Triangle)

Every project has three dimensions: **scope, time, cost**. You can fix any two; the third must flex.

- Fix scope + time → cost flexes (add headcount, contractors)
- Fix scope + cost → time flexes (date slips)
- Fix time + cost → scope flexes (cut features)

**The most common failure**: trying to fix all three. The result is a death march or a missed deadline.

**Communicating the trade-off:**
- "We have a hard date, fixed budget, and full scope" — pick two. Force the third decision early.
- The earlier the trade-off is named, the more options exist for resolving it

## Critical Path and Dependencies

For projects with many interconnected tasks, the **critical path** is the longest sequence of dependent tasks — the one that determines the project's minimum duration.

**Critical path discipline:**
- Identify the critical path during planning (not after slippage)
- Only critical-path tasks affect the end date — slack tasks have float
- Manage critical-path tasks aggressively: assign best people, monitor daily, escalate slips immediately
- Off-critical-path tasks can be deprioritized if needed

**Common dependency failures:**
- Unidentified external dependencies (waiting on legal, vendor, customer signoff)
- Resource conflicts (same person on the critical path of two projects)
- Hidden hand-offs (the work goes "over the wall" with no defined receipt)

## RACI and Decision Rights

A project without owners is a project that fails. RACI (Responsible, Accountable, Consulted, Informed) makes ownership explicit.

**Rules:**
- One A per task (otherwise no accountability)
- R can be multiple (multiple people doing the work)
- Don't overload C (consulting everyone = consulting no one)
- I should be a publish event, not a meeting

**When to use:**
- New projects with cross-functional teams
- After a near-miss caused by ownership confusion
- Annual or quarterly process reviews

Don't RACI everything. For day-to-day work, RACI becomes bureaucratic.

## Scope Management

Scope creep is the most predictable project failure.

**Defense:**
- Write the scope explicitly upfront. What's IN, what's OUT, what's deferred.
- Make scope changes visible — a change request log, reviewed weekly
- Require explicit trade-offs for added scope ("if we add this, what comes out?")
- Sign-off on changes by the project sponsor, not just the project manager

**The "yes, and..." trap:**
- Stakeholder adds "small" requests during execution
- PM accepts to maintain relationship
- Cumulative small adds blow the project
- Counter: aggregate small adds weekly, present them as a batch trade-off

## Estimation — Why We're Bad At It

Estimates are wrong. The question is whether you've learned anything from past wrongness.

**Why estimates fail:**
- Planning fallacy (we under-estimate complexity, over-estimate own capability)
- Unknown unknowns (discovered during work)
- Optimism bias (we hope for the best case)
- Padding politics (engineers pad, managers cut, the padded number wins)

**Better estimation:**
- *Three-point estimation*: best case, most likely, worst case → weighted average ((B + 4M + W) / 6)
- *Reference-class forecasting*: how long did similar projects actually take? Use that, not first-principles estimation.
- *Track actuals vs. estimates* per team — over time, you can calibrate a multiplier (this team consistently estimates at 0.7x of actual)
- *Buffer at the project level, not task level* — adding 20% to each task hides the buffer; a single 20% project buffer is visible and defendable

## Communication and Status Reporting

Status reporting eats more time than the underlying work. Make it efficient.

**Weekly status template (5 minutes to write, 2 minutes to read):**
- *Status*: 🟢 / 🟡 / 🔴 with one-sentence reason
- *Wins this week*: 2-3 bullets
- *Issues / blockers*: 2-3 bullets, each with what's needed to unblock
- *Looking ahead*: top 3 priorities for next week
- *Decisions needed*: 0-3 items, with options and recommendation

Status meetings should exist to resolve blockers, not report status. If the meeting is read-aloud status, kill the meeting and keep the document.

**Color discipline:**
- 🟢 = on track. No issues that affect outcome.
- 🟡 = at risk. Plan exists to recover but not guaranteed.
- 🔴 = off track. Outcome will miss unless something changes.
- Jumping from 🟢 to 🔴 with no 🟡 in between is a process failure. The transition through 🟡 is where intervention is possible.

## Risk Management

Risks identified late are crises; risks identified early are choices.

**Risk register** (live document, reviewed weekly):
- *What could go wrong* (specific, not generic)
- *Likelihood* (1-5)
- *Impact* (1-5)
- *Mitigation plan* (specific action; who owns it; by when)
- *Contingency* (what we do if the risk materializes)

Top risks (likelihood × impact ≥ 12) should have explicit weekly tracking.

**Common risks to look for:**
- Single points of failure (one person, one vendor, one technology)
- External dependencies (legal, regulatory, customer, vendor signoff)
- Scope assumptions that haven't been validated
- Resource availability assumed but not confirmed

## Post-Project Retrospectives

A project without a retrospective is a project that didn't generate learning.

**Format (90 minutes, 6-12 participants):**
1. *What went well* (15 min) — anchor on success first
2. *What could have gone better* (30 min) — without blame
3. *What we learned* (15 min) — generalizable lessons
4. *What we'll do differently* (30 min) — specific, owned action items

**Discipline:**
- Action items must have an owner and a date, or they don't get written
- Retro outputs go to a shared knowledge base, not just to the team
- The next project's plan should reference relevant lessons from prior retros

Without retros, organizations repeat the same project mistakes for years.

## Program Management — When You Have Many Projects

A program is a coordinated set of projects with a shared objective. Program management addresses cross-project dependencies, shared resources, and unified communication.

**Differences from project management:**
- Time horizon: programs run quarters to years
- Outcomes vs. outputs: programs measured by business outcomes; projects measured by completion
- Governance: programs have steering committees and formal stage gates

**When to formalize a program:**
- 3+ projects with shared dependencies
- Cross-functional impact requiring executive coordination
- Outcome that requires multiple deliverables to materialize

Don't formalize programs prematurely. Two related projects can be coordinated without program governance overhead.

## A Final Diagnostic

For any project in flight, ask:
1. Who is the one A (accountable owner)?
2. What's the explicit scope, time, and cost — and which is flexing?
3. What's the critical path?
4. What's the top risk and what's the mitigation?
5. When was the last retrospective on a similar project, and did we apply its lessons?

A "yes" to all five usually means the project is well-run. A "no" or "unsure" on any one is where you should look first when the project starts to slip.
