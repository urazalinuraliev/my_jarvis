"""Executive research workflow.

Mirrors `executive_reflection`'s architecture: a research phase
produces structured findings, then the Executive enters a tool-use
loop with its full outbound toolkit (`_ALL_SKILL_HANDLERS`) and decides
per finding whether to DM a Person, message a department, surface as a
briefing alert, add to the watchlist, schedule a follow-up, or propose
a deeper workflow. The Executive — not the workflow — owns routing.

Entry points:
- ``workflows.executive_research.ExecutiveResearchWorkflow`` — the
  workflow registered in WORKFLOW_REGISTRY. Lives in workflows/ so it
  can import workflows.base + executive_reflection's tool-loop helpers
  without a circular package init.
- ``monitoring.research.dedup.dedup_findings`` — light cross-specialist
  dedup so the Executive synthesis pass doesn't see the same fact twice.
- ``monitoring.research.specialist_research.research_one_specialist`` —
  per-specialist tool-use call.
- ``monitoring.research.scheduler`` — periodic cron + skip-if-unchanged
  gate + onboarding hook (PR-E).
"""
