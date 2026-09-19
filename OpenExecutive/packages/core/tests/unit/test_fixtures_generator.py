"""Validation, serialization, and generation tests for the fixture generator."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from openexecutive.fixtures import generator as gen
from openexecutive.memory.company_profile import CompanyProfile


def _good_bundle_dict() -> dict[str, Any]:
    return {
        "profile": {
            "name": "Acme Robotics",
            "industry": "Warehouse Automation",
            "stage": "Series B",
            "headcount": 120,
            "annual_revenue_arr": 24000000,
            "mission": "Automate the warehouse floor affordably.",
        },
        "people": [
            {
                "full_name": "Jane Doe",
                "role": "CEO",
                "is_principal": True,
                "department_slugs": ["strategy"],
                "authority_scope": ["wildcard", "bogus_scope"],
            },
            {
                "full_name": "Sam Lee",
                "role": "Head of Finance",
                "department_slugs": ["finance"],
            },
        ],
        "departments": [
            {
                "slug": "strategy",
                "title": "Strategy",
                "specialist_key": "cso",
                "head_person_name": "Jane Doe",
                "authority_level": "escalate",
                "charter": {"mission": "Own the competitive read."},
                "goals": [
                    {
                        "period_type": "quarter",
                        "period_value": "Q2 2026",
                        "key_result": "Land 3 enterprise logos",
                        "target": "3",
                        "status": "on_track",
                    }
                ],
            },
            {
                "slug": "finance",
                "title": "Finance",
                "specialist_key": "not_a_real_key",
                "head_person_name": "Sam Lee",
                "charter": {"mission": "Steward cash."},
            },
        ],
        "memory": {
            "decisions": [
                {"timestamp": "2026-01-01T00:00:00+00:00", "domain": "strategy", "summary": "x"}
            ],
            "alerts": [
                {"headline": "Competitor raised", "routed_to_person": "Jane Doe"}
            ],
        },
        "docs": [
            {"filename": "company_overview", "content": "# Overview\nstuff"},
            {"filename": "financials.md", "content": "# Financials\nstuff"},
        ],
    }


def test_validate_good_bundle() -> None:
    bundle = gen.FixtureBundle.model_validate(_good_bundle_dict())
    assert gen.validate_bundle(bundle) == []


def test_validate_missing_head_in_roster() -> None:
    d = _good_bundle_dict()
    d["departments"][0]["head_person_name"] = "Ghost Person"
    bundle = gen.FixtureBundle.model_validate(d)
    errors = gen.validate_bundle(bundle)
    assert any("Ghost Person" in e for e in errors)


def test_validate_alert_recipient_must_exist() -> None:
    d = _good_bundle_dict()
    d["memory"]["alerts"][0]["routed_to_person"] = "Nobody"
    bundle = gen.FixtureBundle.model_validate(d)
    errors = gen.validate_bundle(bundle)
    assert any("Nobody" in e for e in errors)


def test_validate_requires_exactly_one_principal() -> None:
    d = _good_bundle_dict()
    d["people"][1]["is_principal"] = True
    bundle = gen.FixtureBundle.model_validate(d)
    errors = gen.validate_bundle(bundle)
    assert any("is_principal" in e for e in errors)


def test_validate_requires_people() -> None:
    d = _good_bundle_dict()
    d["people"] = []
    bundle = gen.FixtureBundle.model_validate(d)
    errors = gen.validate_bundle(bundle)
    assert any("person" in e for e in errors)


def test_validate_rejects_duplicate_full_name() -> None:
    d = _good_bundle_dict()
    d["people"][1]["full_name"] = "Jane Doe"  # collide with the principal
    d["people"][1]["is_principal"] = False
    bundle = gen.FixtureBundle.model_validate(d)
    errors = gen.validate_bundle(bundle)
    assert any("duplicate full_name" in e for e in errors)


def test_emit_tool_required_keys_match_bundle_fields() -> None:
    # Drift guard: every top-level required key in the hand-written tool schema
    # must be a real FixtureBundle field, so the schema can't silently diverge.
    required = gen._EMIT_TOOL["input_schema"]["required"]
    fields = set(gen.FixtureBundle.model_fields)
    assert set(required) <= fields, set(required) - fields


def test_materialize_rejects_dot_filenames(tmp_path: Path) -> None:
    # A hand-crafted record (bypassing generation) with a ".." doc filename must
    # not escape or crash the load — it lands as a safe .md basename.
    record = {
        "profile_yaml": "company:\n  name: X\n",
        "people_yaml": "people: []\n",
        "departments_yaml": "departments: []\n",
        "memory_json": "{}",
        "docs_json": json.dumps({"..": "evil", "../../escape.md": "nope"}),
    }
    gen.materialize_to_dir(record, tmp_path)
    docs_dir = tmp_path / "docs"
    written = list(docs_dir.glob("*.md"))
    assert len(written) == 2
    # Every doc is a single basename living directly under docs/ — no escape.
    for p in written:
        assert p.parent == docs_dir
        assert "/" not in p.name and p.name not in ("..", ".")
    assert not (tmp_path.parent / "escape.md").exists()


def test_normalize_drops_bad_scope_and_specialist() -> None:
    bundle = gen.FixtureBundle.model_validate(_good_bundle_dict())
    serialized = gen.bundle_to_serialized(bundle, "scenario")
    people = yaml.safe_load(serialized["people_yaml"])["people"]
    jane = next(p for p in people if p["full_name"] == "Jane Doe")
    assert jane["authority_scope"] == ["wildcard"]  # bogus_scope dropped
    depts = yaml.safe_load(serialized["departments_yaml"])["departments"]
    finance = next(d for d in depts if d["slug"] == "finance")
    assert finance["specialist_key"] is None  # invalid key → informational


def test_serialized_profile_roundtrips(tmp_path: Path) -> None:
    bundle = gen.FixtureBundle.model_validate(_good_bundle_dict())
    serialized = gen.bundle_to_serialized(bundle, "scenario")
    p = tmp_path / "profile.yaml"
    p.write_text(serialized["profile_yaml"])
    profile = CompanyProfile.load_from_yaml(p)
    assert profile.name == "Acme Robotics"
    assert profile.annual_revenue_arr == 24000000
    assert serialized["display_name"] == "Acme Robotics"
    assert serialized["doc_count"] == 2


def test_materialize_to_dir_produces_loadable_layout(tmp_path: Path) -> None:
    bundle = gen.FixtureBundle.model_validate(_good_bundle_dict())
    serialized = gen.bundle_to_serialized(bundle, "scenario")
    gen.materialize_to_dir(serialized, tmp_path)

    assert (tmp_path / "profile.yaml").exists()
    assert (tmp_path / "people.yaml").exists()
    assert (tmp_path / "departments.yaml").exists()
    assert (tmp_path / "memory.json").exists()
    # docs/ has the .md-normalized filenames
    docs = sorted(p.name for p in (tmp_path / "docs").glob("*.md"))
    assert docs == ["company_overview.md", "financials.md"]
    # memory.json parses and carries the decision
    mem = json.loads((tmp_path / "memory.json").read_text())
    assert len(mem["decisions"]) == 1


def test_derive_slug_basic() -> None:
    assert gen.derive_slug("Acme Robotics, Inc.") == "acme_robotics_inc"
    assert gen.derive_slug("   ") == "company"


def test_derive_slug_uniqueness() -> None:
    taken = {"acme", "acme_2"}
    slug = gen.derive_slug("Acme", lambda s: s in taken)
    assert slug == "acme_3"


@pytest.mark.asyncio
async def test_generate_uses_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_block = SimpleNamespace(
        type="tool_use", name="emit_fixture", input=_good_bundle_dict()
    )
    response = SimpleNamespace(content=[tool_block])

    class FakeProvider:
        async def messages_create(self, **kwargs: Any) -> Any:
            # forced tool choice must be set
            assert kwargs["tool_choice"]["name"] == "emit_fixture"
            return response

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_provider", lambda model: FakeProvider()
    )
    bundle = await gen.generate_fixture_bundle("a robotics company")
    assert bundle.profile.name == "Acme Robotics"


@pytest.mark.asyncio
async def test_generate_retries_then_fails_on_bad_referential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = _good_bundle_dict()
    bad["departments"][0]["head_person_name"] = "Ghost"
    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="emit_fixture", input=bad)]
    )
    calls = {"n": 0}

    class FakeProvider:
        async def messages_create(self, **kwargs: Any) -> Any:
            calls["n"] += 1
            return response

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_provider", lambda model: FakeProvider()
    )
    with pytest.raises(gen.GenerationError):
        await gen.generate_fixture_bundle("x")
    assert calls["n"] == 2  # one repair retry


@pytest.mark.asyncio
async def test_generate_resolves_model_via_council(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The model passed to the provider comes from the fixture_generator agent's
    effective_model() — default = settings.default_model, overridable via Council."""
    from openexecutive.agents import overrides as ov_mod
    from openexecutive.config import get_settings

    ov_db = tmp_path / "ov.db"
    monkeypatch.setattr(ov_mod, "DB_PATH", ov_db)
    ov_mod.initialize_overrides_db(ov_db)
    ov_mod.invalidate_cache()

    captured: dict[str, str] = {}
    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="emit_fixture", input=_good_bundle_dict())]
    )

    class FakeProvider:
        async def messages_create(self, **kwargs: Any) -> Any:
            captured["model"] = kwargs["model"]
            return response

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_provider", lambda model: FakeProvider()
    )

    await gen.generate_fixture_bundle("a company")
    assert captured["model"] == get_settings().default_model

    # A Council override on fixture_generator flips the model on the next call.
    ov_mod.set_override("fixture_generator", model="claude-haiku-4-5-20251001", model_set=True)
    await gen.generate_fixture_bundle("a company")
    assert captured["model"] == "claude-haiku-4-5-20251001"
    ov_mod.invalidate_cache()


@pytest.mark.asyncio
async def test_generate_raises_without_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="nope")])

    class FakeProvider:
        async def messages_create(self, **kwargs: Any) -> Any:
            return response

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_provider", lambda model: FakeProvider()
    )
    with pytest.raises(gen.GenerationError):
        await gen.generate_fixture_bundle("x")
