# My Jarvis — AI marketing executive

Jarvis is an AI CMO: an [Open Executive](OpenExecutive/README.md) deployment whose
Executive persona is a marketing and growth lead. It can hand multi-agent marketing work
(Instagram content strategy, meeting briefings) to a CrewAI crew.

| Directory | What it is | Upstream |
|---|---|---|
| [`OpenExecutive/`](OpenExecutive/) | The app: FastAPI backend + Next.js UI, the Executive and its specialist agents, and the Telegram/Slack/Discord/email channels. | [SenteLabsAI/OpenExecutive](https://github.com/SenteLabsAI/OpenExecutive) (Apache-2.0) |
| [`Smart-Marketing-Assistant-Crew-AI/`](Smart-Marketing-Assistant-Crew-AI/) | The CrewAI crews: `instagram` (research → strategy → visuals → copy → report) and `meeting_prep`. | [praj2408/Smart-Marketing-Assistant-Crew-AI](https://github.com/praj2408/Smart-Marketing-Assistant-Crew-AI) |
| [`ai-marketing-skills/`](ai-marketing-skills/) | 18 marketing skills (competitor, keyword and channel research, content strategy, ad angles, conversion and SEO audits, …), imported into OpenExecutive's builtin skills by `OpenExecutive/packages/core/scripts/import_marketing_skills.py`. | [superamped/ai-marketing-skills](https://github.com/superamped/ai-marketing-skills) (MIT) |

Each directory keeps its full git history, imported with `git subtree`.

## Running it

```bash
git clone https://github.com/urazalinuraliev/my_jarvis.git
cd my_jarvis/OpenExecutive
cp .env.example .env        # set ANTHROPIC_API_KEY (+ TELEGRAM_* for the bot)
make dev                    # API on :8000, UI on :3000
```

OpenExecutive finds the crew repo next to itself, so it needs no configuration in this
layout. Set `CREWAI_REPO_PATH` only if you move the crew repo somewhere else. You can
run a crew in three ways:

- In chat: ask for an Instagram content plan. The Executive starts the `run_crew` tool,
  and the result appears on the Jobs page.
- From the terminal: `openexecutive crew --crew instagram --task "summer launch campaign"`
- In Telegram: `/strategy summer launch campaign`. The report comes back as messages and
  `.md` files.

The crews' model is `CREWAI_MODEL`, or the Claude `DEFAULT_MODEL` by default.
Deliverables are written to `CREW_OUTPUT_DIR` (default `crew_runs/`). See
`OpenExecutive/.env.example`.

Jarvis finds the marketing skills itself (`search_skills` / `load_skill`). The research
skills need web search: `ENABLE_WEB_SEARCH=true` (the app default; `.env.example` ships it
off). The keyword skills also need the Keywords Everywhere MCP server, and the
page-rendering skills can use Playwright MCP; see `ai-marketing-skills/integrations/`.
Don't give Playwright `--allow-unrestricted-file-access` on a server that holds `.env` or
credentials, because the model could then open any local file. After updating
`ai-marketing-skills/`, re-run the importer and commit the result.

## Where to read next

- `OpenExecutive/CLAUDE.md`: architecture, conventions, and the PR checklist.
- `OpenExecutive/packages/core/openexecutive/integrations/crewai_adapter.py`: how
  OpenExecutive runs the crews.
- `OpenExecutive/packages/core/openexecutive/architecture/architecture-facts.yaml`, key
  `integrations.crewai_crews`.
- Run the unit tests from a checkout that has no `.env` above it, because they write to
  the default database paths. See "Local data gotcha" in `OpenExecutive/CLAUDE.md`.
