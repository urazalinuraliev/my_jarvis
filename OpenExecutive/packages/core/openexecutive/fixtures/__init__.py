"""User-generated company fixtures (DB-backed).

The four curated fixtures under repo-root ``fixtures/companies/`` stay as
git-tracked YAML seeds. Fixtures a user generates from a natural-language
scenario live in the ``generated_fixtures`` SQLite table on the Fly volume
so they persist across redeploys (disk-only fixtures would be wiped on every
deploy). Both sources are merged by the ``/fixtures`` list/load endpoints.

* ``store``     — the ``generated_fixtures`` table + CRUD.
* ``generator`` — LLM generation + validation into a ``FixtureBundle``.
"""
