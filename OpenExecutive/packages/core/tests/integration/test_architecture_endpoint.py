"""Integration tests for the static /architecture endpoints.

Content is served from the pre-authored architecture/prebuilt/*.json
files — there is no LLM call and no database on this path.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from openexecutive.api.main import app
from openexecutive.architecture.sections import SECTIONS


@pytest.fixture()
def client() -> TestClient:
    # The app installs a shared-secret gate when BACKEND_SHARED_SECRET is
    # set; send the matching header so these tests pass whether or not the
    # developer's environment configures one.
    secret = os.environ.get("BACKEND_SHARED_SECRET", "").strip()
    headers = {"x-api-key": secret} if secret else {}
    return TestClient(app, headers=headers)


def test_list_sections_lists_every_registry_section(client: TestClient) -> None:
    res = client.get("/architecture/sections")
    assert res.status_code == 200
    body = res.json()
    assert "sections" in body
    assert len(body["sections"]) == len(SECTIONS)
    ids = {s["id"] for s in body["sections"]}
    assert {"overview", "api"} <= ids
    # Every section ships with pre-authored content.
    assert all(s["fresh"] for s in body["sections"])
    assert all(s["generated_at"] for s in body["sections"])


def test_get_section_unknown_404(client: TestClient) -> None:
    res = client.get("/architecture/sections/does-not-exist")
    assert res.status_code == 404


def test_get_section_returns_static_content(client: TestClient) -> None:
    res = client.get("/architecture/sections/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["section_id"] == "overview"
    assert body["markdown"].strip()
    # The served payload is the static shape — no generation metadata.
    assert "facts_hash" not in body
