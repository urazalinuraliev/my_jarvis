"""Auth-facing surface — the People roster as the source of truth for who
can sign in via Google OAuth on the UI.

The Next.js layer's ``auth.ts`` calls ``GET /auth/allowed-emails`` during
the NextAuth ``signIn`` callback to decide whether to admit a logged-in
Google user. Previously the allowlist lived in the ``ALLOWED_EMAILS``
env var on the UI; pulling it from the people store means managing
access is the same operation as managing your team.

This route is still gated by the shared-secret middleware — the UI's
server-side fetch carries ``x-api-key`` so an unauthenticated caller
can't enumerate emails.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from openexecutive.people import store as people_store

router = APIRouter()


class AllowedEmail(BaseModel):
    email: str
    person_id: int


@router.get("/auth/allowed-emails", response_model=list[AllowedEmail])
def allowed_emails() -> list[AllowedEmail]:
    """Return ``[{email, person_id}]`` for every non-archived Person with an email.

    Empty list when no people are seeded yet (fresh install). In that case the
    UI's ``auth.ts`` is expected to fall back to its ``ALLOWED_EMAILS`` env
    var so a brand-new operator can sign in and run onboarding. Once any
    Person exists with an email, this endpoint becomes authoritative.
    """
    return [
        AllowedEmail(email=p.email.lower(), person_id=p.id)  # type: ignore[arg-type]
        for p in people_store.list_people()
        if p.email and p.id is not None
    ]
