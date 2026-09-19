"""Shared LLM factory for every crew in this repo.

A host app can hand over the model and API key in-process with
:func:`configure`. Otherwise the model comes from ``CREWAI_MODEL`` (a CrewAI
model string such as ``anthropic/claude-sonnet-5``) and CrewAI reads the
provider's key from the environment as usual.
"""
import os

from crewai import LLM

DEFAULT_MODEL = "anthropic/claude-sonnet-5"

_configured = {}


def configure(*, model=None, api_key=None):
    """Set the model and API key for every agent built after this call.

    Each call replaces both; None falls back to the environment.
    """
    _configured.update(model=model, api_key=api_key)


def _env_model():
    value = os.environ.get("CREWAI_MODEL", "").strip()
    # "# ..." is an inline .env comment that dotenv kept as the value.
    return None if value.startswith("#") else value or None


def build_llm() -> LLM:
    model = _configured.get("model") or _env_model() or DEFAULT_MODEL
    api_key = _configured.get("api_key")
    if api_key:
        return LLM(model=model, api_key=api_key)
    return LLM(model=model)
