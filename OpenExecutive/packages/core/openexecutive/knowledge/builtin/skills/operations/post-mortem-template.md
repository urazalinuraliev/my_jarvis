---
name: post-mortem-template
description: Blameless post-mortem for an incident, outage, or significant failure — timeline, root cause, action items
when_to_use: User asks for a post-mortem (RCA), incident review, retrospective on a specific failure, or "what should we cover in the post-mortem for [incident]"
category: operations
---

# Post-Mortem Template

A post-mortem turns failure into learning. Done well, it changes future behavior. Done badly, it generates a document nobody reads, with action items nobody completes, and the same incident happens again in 6 months.

## The blameless principle

The most important rule: focus on systems and processes, not on individuals.

- People act based on what they know in the moment with the tools available
- "Why did Alice make that change?" → "Why did the system allow that change without verification?"
- The goal is preventing recurrence, not assigning blame
- Blame culture causes people to hide failures next time

## Inputs to gather first

Before drafting, confirm:

1. **The incident** — what happened, when it started, when resolved
2. **The impact** — customer-facing (outage, errors, data loss), financial, reputational
3. **The detection** — how was it discovered (alert, customer report, accident)
4. **The response** — who responded, what was tried, how it was resolved
5. **The available data** — logs, monitoring, communications, decisions made

If the data is incomplete, capture what's known and explicitly note gaps.

## Output structure

### 1. Summary (1 paragraph)

The 2-3 sentence version. What happened, the impact, the root cause.

Example: "On May 10, 2026, between 14:32 and 16:18 UTC, our API returned 5xx errors for ~40% of customer requests. Root cause was a database migration that locked tables longer than expected during peak traffic. 12 enterprise customers experienced significant disruption; one filed an SLA credit claim."

### 2. Impact

Specific. Quantified where possible.

- **Customer impact**: # of customers affected, % of traffic affected, nature of impact (errors, latency, data loss, feature unavailable)
- **Duration**: start time, detection time, mitigation time, full resolution time
- **Revenue impact**: SLA credits owed, lost revenue, refunds issued
- **Other**: support ticket volume, social media mentions, press attention

### 3. Timeline

Chronological log of significant events.

Format:
| Time (UTC) | Event |
|---|---|
| 14:32 | Migration started in production |
| 14:35 | First 5xx errors reported |
| 14:42 | First alert fired |
| 14:51 | On-call engineer paged |
| 15:03 | Incident commander assigned |
| 15:18 | Migration rolled back |
| 15:42 | Error rate returned to baseline |
| 16:18 | All customer-impacting effects resolved |
| 18:45 | Customer comms sent |

Discipline:
- Use the actual times from logs / Slack / paging system
- Note the gaps and what happened during them (especially: time-to-detection, time-to-mitigation)
- Include both technical events and communication events

### 4. Root cause

The underlying cause, not the surface trigger.

**Use the "5 Whys"**:
- Why did the system go down? → DB migration locked tables
- Why did the migration lock tables? → Migration used non-concurrent index creation
- Why was non-concurrent chosen? → Engineer not aware of the pattern; documentation incomplete
- Why was the documentation incomplete? → No process to update runbooks after similar past incident
- Why no process? → Runbook ownership not assigned after team restructure

Root cause: organizational (process), not individual (the engineer).

For most incidents, the root cause traces back to systems, processes, or organizational factors — not to a single decision by a single person.

### 5. What went well

The retrospective half people skip. There's almost always something.

- Detection sources (alerts that fired correctly)
- Response coordination (incident commander, comms)
- Specific decisions that limited blast radius
- Tools or processes that worked as designed

This isn't decoration. It identifies what to preserve as you change other things.

### 6. What went poorly

The hard part. Be specific and honest.

- Where was the gap between expectation and reality?
- What did the team not know that they should have?
- What tools were missing or inadequate?
- Where did communication break down?
- Where did processes fail?

Discipline:
- Specific incidents, not generic ("communications were unclear" → "the customer comms were sent 3 hours after resolution because no one owned that step")
- Systemic, not personal
- Honest, not defensive

### 7. Action items

Specific, owned, dated. The most important section.

| Action | Owner | Due Date | Priority |
|---|---|---|---|
| Add concurrent index creation to migration template | DB team lead | 2026-05-20 | P0 |
| Add automated check for long-running migrations | Infra team | 2026-06-01 | P1 |
| Update runbook for production migrations | DB team lead | 2026-05-15 | P0 |
| Reduce alert latency from 10 min to 2 min | Observability | 2026-06-15 | P1 |
| Pre-draft customer comms templates for outages | Support lead | 2026-05-30 | P1 |

Discipline:
- Each action item has a specific owner (not "the team")
- Each has a specific due date
- Priority noted (P0 = within 1-2 weeks; P1 = within 1 month; P2 = longer)
- Tracked to completion (this is often where post-mortems fail — action items go to a graveyard)

### 8. Lessons (generalizable)

What patterns from this incident apply beyond this specific failure?

- "Database migrations are higher risk than we treated them"
- "Our incident response works for technical recovery; customer comms lag"
- "Alerting latency masks the true time-to-detection"

These lessons inform future planning, training, and architectural decisions.

## Discipline

- **Write within 5 business days of resolution.** Memory degrades; lessons are lost.
- **Blameless throughout.** "Alice deployed bad code" → "The deploy process allowed a change without integration test."
- **Quantified impact.** Subjective severity is unreliable.
- **Action items owned and dated.** Without ownership and dates, nothing happens.
- **Distributed widely.** Internal post-mortems should be read across teams — not just the one that owned the incident.
- **Tracked to completion.** Action items reviewed at +30 and +90 days; closed-out or escalated.

## Sharing externally

For customer-impacting incidents, consider a public-facing post-mortem:

- Acknowledges the issue and impact
- Provides honest explanation (without exposing security details)
- Shows what's changing to prevent recurrence
- Often increases customer trust more than the incident damaged it

Examples done well: Cloudflare, GitLab, GitHub — public post-mortems are part of their brand.

Don't share when:
- Security-sensitive details would create risk
- Litigation is plausible (legal review)
- Customer privacy at stake

## What NOT to include

- Individual blame ("Alice deployed bad code")
- Vague descriptions ("things broke for a while")
- Action items without owners or dates
- Defensive framing ("the customer experienced minor degradation")
- "We will be better" without specifics
- Recurrence of the same lessons from prior post-mortems without acknowledgment

## The post-mortem review

Once written, the team reviews together (often 60-90 min):
- Walk through the timeline
- Validate the root cause
- Debate and refine action items
- Assign and commit to ownership
- Identify what's missing

This is also the most important blameless moment — the discussion sets the tone for whether future incidents will be surfaced honestly.

## Closing summary

End the post-mortem with three sentences:

1. The single most important systemic lesson
2. The action item that, if completed, would prevent the most likely recurrence
3. When and how the team will revisit the action items (typically 30-day and 90-day reviews)
