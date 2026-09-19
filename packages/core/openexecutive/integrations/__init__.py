"""External-framework integration adapters.

Each subpackage wraps a third-party agent framework (CrewAI, LangGraph, etc.)
behind a uniform interface so the Executive can invoke multi-agent workflows
as ordinary skill tools without leaking framework specifics into the core
orchestration loop.
"""