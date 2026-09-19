# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-30

Initial public release.

### Added
- Multi-agent "Executive" system: a single coherent executive persona backed by
  eight specialist sub-agents, powered by the Anthropic Claude API.
- Python backend (`packages/core`) — FastAPI service, orchestrator, specialist
  agents, ChromaDB-backed RAG, CLI, and prompt-caching layer.
- Next.js 15 web UI (`packages/ui`), including the static `/architecture` page.
- Curated MBA knowledge base (`knowledge/`) and eval suite (`evals/`).
- Optional integrations: Slack, Discord, and email.
- Docker and Fly.io deployment configuration.
- Open-source project setup: Apache-2.0 license, contribution guide, code of
  conduct, security policy, issue/PR templates, and CI.

[Unreleased]: https://github.com/SenteLabsAI/OpenExecutive/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SenteLabsAI/OpenExecutive/releases/tag/v0.1.0
