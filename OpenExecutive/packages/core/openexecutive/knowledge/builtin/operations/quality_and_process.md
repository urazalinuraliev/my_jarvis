# Quality and Process Improvement

Operational excellence is the discipline of doing the same thing well, repeatedly, with measured improvement. The frameworks below come from manufacturing but apply to any repeated process — software incident response, customer onboarding, support ticket flow, sales operations.

## The Two Schools

**Six Sigma** — reduce variation. The fewer defects per million opportunities (DPMO), the better the process.
- Originated at Motorola; popularized by GE
- Target: 3.4 defects per million (Six Sigma level)
- Strong in: regulated industries, manufacturing, repeatable services
- Methodology: DMAIC (see below)

**Lean** — eliminate waste. Anything that doesn't add customer value is waste.
- Originated at Toyota; "Toyota Production System"
- Eight forms of waste: defects, overproduction, waiting, non-utilized talent, transportation, inventory, motion, extra-processing (DOWNTIME)
- Strong in: high-throughput operations, software development (Lean Startup, Lean UX)
- Methodology: value stream mapping, Kaizen, just-in-time

**Lean Six Sigma** combines both. Most modern operations programs use elements of each.

## DMAIC — The Process Improvement Workhorse

Define → Measure → Analyze → Improve → Control. Five phases for systematic improvement of an existing process.

### Define
- What is the problem? (Specific, measurable, customer-impacting)
- Who is the customer of this process? (Internal or external)
- What is the scope (start and end of the process)?
- Who is on the improvement team?

Output: project charter

### Measure
- What is the current performance? (Baseline)
- What is the customer's expectation? (Target)
- How will we measure ongoing? (Operational definitions of metrics)

Common metrics: cycle time, defect rate, throughput, cost per unit, customer satisfaction

Output: baseline measurement, data collection plan

### Analyze
- What's actually happening? Map the current process step-by-step (often with a swimlane diagram)
- Where are the bottlenecks, waste, defect sources?
- What's the root cause? (See "5 Whys" below)

Tools: Pareto charts (80% of defects from 20% of causes), fishbone diagram (Ishikawa), process maps, statistical analysis

Output: validated root cause(s)

### Improve
- Generate solutions for the root cause
- Pilot the highest-leverage solution
- Measure the impact
- Iterate

Discipline: solve the root cause, not a symptom. A symptom-fix returns to bite you.

Output: implemented solution with measured improvement

### Control
- Standardize the new process (documentation, training)
- Build monitoring to catch regression
- Hand off to the process owner

Without Control, improvements decay within 6-12 months. The new way drifts back to the old way unless monitored.

## 5 Whys — The Root Cause Tool

When something goes wrong, ask "why?" five times. The first answer is the symptom; the fifth is usually the root cause.

**Example: customer-impacting outage**
1. *Why did the system go down?* The database ran out of disk space.
2. *Why did it run out?* Log retention was set too high.
3. *Why was retention too high?* Engineer set it during onboarding without reviewing defaults.
4. *Why was the default wrong?* No one revisits configuration defaults after initial setup.
5. *Why don't we revisit defaults?* No process exists to review infrastructure config quarterly.

Fix at level 5 (institute quarterly config review), not level 1 (add disk).

5 Whys is shallow if applied mechanically. Pair it with data — ask "why" of patterns, not single incidents.

## Theory of Constraints (Goldratt)

A system's throughput is limited by its single biggest constraint (bottleneck). All other improvements are irrelevant until you address the constraint.

**Five focusing steps:**
1. **Identify** the system's constraint
2. **Exploit** the constraint (get more out of the existing bottleneck before adding capacity)
3. **Subordinate** everything else to the constraint (don't optimize non-bottleneck processes — it just creates inventory)
4. **Elevate** the constraint (add capacity, redesign, automate)
5. **Repeat** — once that constraint is broken, find the next one

**Why this matters:**
- Most "efficiency" programs improve non-bottleneck areas and produce no overall throughput improvement
- A non-bottleneck running at 100% utilization is overproducing waste
- Saying "no" to optimization that doesn't move the constraint is the discipline

Applies to: sales (which stage drops the most pipeline?), support (which channel has the longest queue?), engineering (which step in the deploy pipeline takes longest?), customer success (which onboarding step has the highest abandonment?).

## Kaizen — Continuous Small Improvements

The Japanese principle of continuous improvement through small, incremental changes. The opposite of the "big transformation initiative."

**Kaizen principles:**
- Improvements come from the people doing the work, not from consultants
- Many small improvements compound; rare big ones are riskier
- Improvements are tested in small doses, scaled if they work
- Documentation and standardization are part of the improvement

**Operational form:**
- Weekly team retros with action items
- Monthly process reviews
- Quarterly cross-team improvement events ("Kaizen events")

The cultural prerequisite: psychological safety. People will only surface what's broken if they trust they won't be punished for it.

## Value Stream Mapping

Walk a process end-to-end and document every step, every wait, every handoff, every defect-creating step.

**For each step, record:**
- Process time (how long the work takes)
- Wait time (queue before this step)
- Defect rate (what % needs rework)
- Who does it

**Identify:**
- Value-added time vs. total cycle time (often 5-15% — the rest is waste)
- Handoffs (each one is a defect opportunity)
- Rework loops (work going backwards)

**Common findings:**
- Most cycle time is waiting, not working
- Most defects come from a small number of steps
- Some steps add no value to the customer

VSM is most powerful when the team that owns the process is in the room. The map is the start; the action items from "what would you change?" are the value.

## Operational Metrics — DORA, Lean, and Service

**DORA (DevOps Research & Assessment) for engineering:**
- Deployment frequency
- Lead time for changes (commit to production)
- Change failure rate
- Mean time to recovery (MTTR)

Elite performers: deploy multiple times per day, lead time <1 hour, change failure rate <15%, MTTR <1 hour. Most companies are nowhere near.

**Lean metrics for any process:**
- Cycle time (start to finish)
- Throughput (units per period)
- Work-in-progress (WIP)
- Defect rate

**Service-line metrics:**
- First-response time
- Time to resolution
- First-contact resolution rate
- Customer satisfaction (CSAT) per ticket
- Escalation rate

Pick 3-5 metrics per function. More than that and the team optimizes for measurement, not outcomes.

## When Process Hurts

Process is a tool, not a virtue. Over-processing is itself one of the eight lean wastes.

**Signs of over-process:**
- More time spent reporting on work than doing it
- Approval chains for decisions that have no real downside
- "We've always done it that way" with no current rationale
- Process steps that nobody can explain the purpose of

**The pruning discipline:**
- Annual process audit: which steps still add value?
- Sunset by default: if no one can defend the value, kill the step
- Replace prescriptive process with judgment + transparent post-hoc review where possible

Mature organizations have lighter process than mid-stage ones, because they've pruned. New organizations have no process at all and survive on heroics, which doesn't scale.

## The Operations Diagnostic

For any operational function, ask:
1. What is the customer of this process getting? Is the process serving them?
2. What's the cycle time and the defect rate? Are they trending?
3. Where is the constraint? What's the plan to elevate it?
4. What process steps did we add last year? What did we kill? (If addition >> deletion, you're accreting bureaucracy)
5. Who owns improvement? Does anyone wake up thinking about making this process better?

Operations is a craft. Treat it that way and the gains compound.
