"""Talent / executive-search core.

The talent-intelligence platform built on Open Executive — in-house hiring,
where searches are run *within* this company (not on behalf of external
clients). Two entities:

- ``Engagement`` — one search: a role we're hiring for in this company.
- ``Candidate`` — a person being considered for an engagement, moving through
  the pipeline ``lead → screened → interviewed → offer → placed`` (or
  ``rejected``).

Persistence mirrors ``openexecutive.people`` exactly: SQLite tables created
idempotently in the shared ``episodic_memory.db``, with a ``_resolve_db_path``
indirection so tests can monkeypatch ``DB_PATH``. See ``docs/talent-platform-
scoping.md`` for how this fits the broader roadmap.
"""
