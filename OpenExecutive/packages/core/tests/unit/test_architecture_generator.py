"""Unit tests for the generator's pure helpers + the streaming event path.

No real Anthropic/OpenRouter calls — the streaming test mocks the provider.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from openexecutive.architecture.facts import FactsBundle
from openexecutive.architecture.generator import (
    _bad_output_content,
    _build_section_content,
    _parse_response,
    _sanitise_mermaid,
    _strip_code_fence,
    _validate_mermaid,
    stream_generate_section,
)
from openexecutive.architecture.sections import get_section


def _bundle() -> FactsBundle:
    return FactsBundle(
        curated={},
        curated_mtime=0.0,
        agents=[],
        workflows=[],
        api_endpoints=[],
        health={},
        code_excerpts=[],
        kb_chunks={},
    )


def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


class _FakeStream:
    """Async context manager + async iterable mimicking the provider stream
    surface that BOTH AnthropicProvider and OpenRouterProvider expose
    (content_block_delta events) — deliberately NOT the SDK-only
    `text_stream` attribute the generator used to depend on."""

    def __init__(self, events: list) -> None:
        self._events = events

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def __aiter__(self):
        for e in self._events:
            yield e


def test_stream_generate_section_consumes_provider_neutral_events() -> None:
    # Chunks concatenate to valid section JSON; a non-text event must be ignored.
    events = [
        _text_delta('{"markdown": "Hel'),
        SimpleNamespace(type="message_delta"),  # not a text delta -> skipped
        _text_delta('lo", "mermaid": null}'),
    ]
    fake_provider = SimpleNamespace(messages_stream=lambda **_kw: _FakeStream(events))
    spec = get_section("overview")

    async def _collect() -> list[dict]:
        out: list[dict] = []
        with patch(
            "openexecutive.architecture.generator.get_provider",
            return_value=fake_provider,
        ):
            async for item in stream_generate_section(spec, _bundle()):
                out.append(item)
        return out

    items = asyncio.run(_collect())
    deltas = [i["text"] for i in items if i["type"] == "delta"]
    assert deltas == ['{"markdown": "Hel', 'lo", "mermaid": null}']  # non-text skipped
    done = [i for i in items if i["type"] == "done"]
    assert len(done) == 1
    assert done[0]["content"]["markdown"] == "Hello"


def test_strip_code_fence_handles_json_fenced_response() -> None:
    raw = '```json\n{"markdown": "x", "mermaid": null}\n```'
    assert _strip_code_fence(raw).startswith("{")


def test_parse_response_strips_control_chars() -> None:
    # \x01 is a control char that's neither tab/newline nor valid JSON whitespace.
    raw = '{"markdown":"hi\x01there","mermaid":null}'
    parsed = _parse_response(raw)
    assert parsed["markdown"] == "hithere"


def test_validate_mermaid_flowchart_and_sequence() -> None:
    overview = get_section("overview")  # diagram_kind=flowchart
    lifecycle = get_section("lifecycle")  # diagram_kind=sequence
    assert _validate_mermaid("flowchart TD\nA-->B", overview) is True
    assert _validate_mermaid("graph LR\nA-->B", overview) is True
    assert _validate_mermaid("sequenceDiagram\nA->>B: x", overview) is False
    assert _validate_mermaid("sequenceDiagram\nA->>B: x", lifecycle) is True
    assert _validate_mermaid("flowchart TD\nA-->B", lifecycle) is False


def test_sanitise_mermaid_drops_click_and_html() -> None:
    """The LLM-generated diagram is rendered with Mermaid `securityLevel:
    'loose'`. Any `click` directive becomes JS execution, and any HTML
    other than `<br/>` becomes an injection vector. Both must be
    stripped before the diagram reaches the cache."""
    hostile = (
        'flowchart TD\n'
        '  A["<img src=x onerror=alert(1)>"] --> B\n'
        '  click A href "javascript:alert(1)"\n'
        '  click B callExternal\n'
        '  C["one<br/>two"] --> D'
    )
    safe = _sanitise_mermaid(hostile)
    assert "click " not in safe.lower()
    assert "onerror" not in safe
    assert "<img" not in safe
    # The benign <br/> line-break inside the label must survive.
    assert "<br/>" in safe


def test_build_section_content_drops_mermaid_when_not_wanted() -> None:
    schemas = get_section("schemas")  # wants_mermaid=False
    parsed = {"markdown": "body", "mermaid": "flowchart TD\nA-->B"}
    content = _build_section_content(schemas, _bundle(), parsed)
    assert content.mermaid is None
    assert content.markdown == "body"


def test_build_section_content_drops_invalid_mermaid() -> None:
    overview = get_section("overview")
    parsed = {"markdown": "body", "mermaid": "this is not mermaid"}
    content = _build_section_content(overview, _bundle(), parsed)
    assert content.mermaid is None


def test_build_section_content_keeps_valid_sanitised_mermaid() -> None:
    overview = get_section("overview")
    parsed = {"markdown": "body", "mermaid": "flowchart TD\n  A --> B\n  click A bad"}
    content = _build_section_content(overview, _bundle(), parsed)
    assert content.mermaid is not None
    assert content.mermaid.startswith("flowchart")
    assert "click " not in content.mermaid.lower()


def test_bad_output_content_truncates() -> None:
    raw = "x" * 5000
    out = _bad_output_content(get_section("overview"), _bundle(), raw)
    assert out.mermaid is None
    # The truncation budget is 1200 chars; the rendered markdown must
    # not include all 5000.
    assert len(out.markdown) < 2000
