# Self-hosted Honcho on Fly

OE's per-person memory layer ([honcho.dev](https://honcho.dev)) runs as a
private Fly app. The OE API talks to it over Fly's internal network; it
has no public IP. This runbook covers first-time provisioning, day-2
operations, and version bumps.

OE-side wiring lives in
[`packages/core/openexecutive/memory/honcho_client.py`](../packages/core/openexecutive/memory/honcho_client.py)
and is gated by `HONCHO_ENABLED`. Until that flag flips to `true` in
`openexec-api-dev`'s secrets, OE behaves identically to before.

## Architecture

```
openexec-api-dev (Fly app)
    │
    │ POST/GET via httpx → http://openexec-honcho-dev.flycast:8000
    ▼
openexec-honcho-dev (Fly app, this runbook)
    ├── api process     — FastAPI on :8000, internal-only
    ├── deriver process — background worker; runs extraction + dreaming
    ├── embed process   — local OpenAI-compatible embeddings sidecar on :8001
    │                     (fastembed + BAAI/bge-small-en-v1.5). No external
    │                     embedding vendor; deriver reaches it via
    │                     embed.process.openexec-honcho-dev.internal:8001
    └── Postgres        — Fly Postgres with pgvector, attached

All LLM calls (deriver, summary, dialectic levels, dream deduction) go
out via OpenRouter using Honcho's `openai` transport with a custom
`base_url`. Single outbound credential (`LLM_OPENAI_API_KEY` = OE's
existing OpenRouter key). Models are OpenRouter slugs in OE's existing
convention (dotted, matching `packages/core/openexecutive/providers/
registry.py`): `anthropic/claude-haiku-4.5` for cheap-tier work
(deriver / summary / dialectic minimal+low) and
`anthropic/claude-sonnet-4.6` for medium+high+max dialectic and dream
deduction.
```

## First-time provisioning

Everything below assumes you have `flyctl` and an authenticated `fly`
org. Run from the repo root.

### 1. Create the app

```bash
flyctl apps create openexec-honcho-dev --org <your-org>
```

### 2. Stand up Postgres with pgvector

Fly's managed Postgres ships pgvector out of the box on recent images.

```bash
# Create a 1-vCPU / 1GB Postgres cluster in iad.
flyctl postgres create \
    --name openexec-honcho-pg \
    --region iad \
    --org <your-org> \
    --vm-size shared-cpu-1x \
    --volume-size 10

# Attach to the Honcho app. This creates a DATABASE_URL secret on
# openexec-honcho-dev.
flyctl postgres attach openexec-honcho-pg -a openexec-honcho-dev

# Enable pgvector. Honcho's migrations expect the extension to exist.
flyctl postgres connect -a openexec-honcho-pg \
    -- -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

Honcho's config expects `DB_CONNECTION_URI` with the SQLAlchemy
psycopg driver scheme; Fly Postgres attach injects `DATABASE_URL=postgres://...`
which the psycopg dialect lookup rejects. Rewrite the scheme during the
alias step:

```bash
RAW_URL=$(flyctl ssh console -a openexec-honcho-dev -C 'printenv DATABASE_URL')
SQLA_URL=$(echo "$RAW_URL" | sed 's|^postgres://|postgresql+psycopg://|')
flyctl secrets set -a openexec-honcho-dev DB_CONNECTION_URI="$SQLA_URL"
```

(Yes, the ssh-into-the-machine-just-to-read-an-env-var step is ugly —
Fly's secrets API doesn't let you read a secret you've already set, and
without the scheme rewrite the API crashes at first DB connect with
"Can't load plugin: sqlalchemy.dialects:postgres". The runbook copy is
here so nobody has to figure it out twice.)

### 3. Set the remaining secrets

OpenRouter is the only outbound LLM vendor — same account OE already
uses. Embeddings come from the local `embed` process group (no key
needed for the sidecar itself, but Honcho's OpenAI client requires
*some* API key string, so we pass a placeholder).

```bash
flyctl secrets set -a openexec-honcho-dev \
    LLM_OPENAI_API_KEY="$OPENROUTER_API_KEY" \
    AUTH_JWT_SECRET="$(openssl rand -hex 32)" \
    EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL="http://embed.process.openexec-honcho-dev.internal:8001/v1" \
    EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY="local-no-auth-needed" \
    EMBEDDING_VECTOR_DIMENSIONS=384 \
    DERIVER_WORKERS=2 \
    SENTRY_ENABLED=false
```

Why this exact set of variables:

- `LLM_OPENAI_API_KEY` holds an OpenRouter key because Honcho's
  `openai` transport accepts any OpenAI-format endpoint (verified
  against `src/llm/registry.py:73`). `config.toml` sets the per-slot
  `base_url` to OpenRouter for every LLM call, so the client
  authenticates with OpenRouter's key but speaks OpenAI's wire
  format. Consolidates dev billing onto your existing OpenRouter
  account.
- `EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL` uses Honcho's
  nested-pydantic-settings convention (`env_prefix="EMBEDDING_"`,
  `env_nested_delimiter="__"`). The path is
  `EmbeddingSettings.MODEL_CONFIG.overrides.base_url`. **Plain
  `EMBEDDING_BASE_URL` is silently ignored** — verified against
  Honcho's settings loader. Same convention for the dummy API key.
- `EMBEDDING_VECTOR_DIMENSIONS=384` matches bge-small-en-v1.5's
  output dim. Honcho's default schema is `Vector(1536)`; without
  this override AND the corresponding `configure_embeddings.py`
  ALTER (run automatically by Fly's `release_command`, see step 4),
  the deriver crashes on every embed call with a dimension
  mismatch.
- `DERIVER_WORKERS=2` lifts Honcho's default of 1 (`DeriverSettings.WORKERS`
  per `src/config.py:736`). Two workers handle the bursty extraction +
  dreaming load comfortably on the 2GB deriver VM.

Store `AUTH_JWT_SECRET` in a password manager — every issued
`HONCHO_API_KEY` (set in step 5) is derived from it, so a rotation
invalidates everything.

### 4. Deploy

```bash
flyctl deploy -c fly.honcho.toml
```

Fly's `[deploy].release_command` (configured in `fly.honcho.toml`) runs
`python scripts/provision_db.py && python scripts/configure_embeddings.py --yes`
in a one-shot machine **before** the new release machines become
active. That covers:

- Schema migrations (Alembic under the hood; idempotent — no-ops when
  nothing changed)
- `configure_embeddings.py` ALTERs the pgvector column dim to match
  `EMBEDDING_VECTOR_DIMENSIONS` from your secrets. Also idempotent.

If the release_command fails the deploy aborts and the previous
release stays active — you won't end up with a half-migrated database
serving a new image. Verify everything came up:

```bash
flyctl status -a openexec-honcho-dev
# Expect three machines: one running `api`, one `deriver`, one `embed`.
```

### 5. Generate an API key + wire OE

Honcho v3.0.7 does not ship a token-minting CLI command. Use the
`create_admin_jwt()` Python helper from inside the running api container
— it reads `AUTH_JWT_SECRET` from the environment and returns a signed
admin JWT good against every workspace:

```bash
flyctl ssh console -a openexec-honcho-dev --process-group api \
    -C 'python -c "from src.security import create_admin_jwt; print(create_admin_jwt())"'
# Outputs: eyJ... (a JWT string — use this verbatim as HONCHO_API_KEY)
```

**Security note**: an admin JWT is a master key for the entire Honcho
instance — it can read any peer's memory, mint new tokens, and rotate
keys. Using one as `HONCHO_API_KEY` in dev means anyone with read access
to `openexec-api-dev`'s Fly secrets can take over the Honcho deployment.
For a strictly-isolated dev environment that's acceptable, but if dev
secrets sit next to any real-user PII pipe (a live Slack workspace, a
shared Discord server), treat that as production and skip straight to
workspace-scoped tokens.

For prod, mint a workspace-scoped key by hitting `POST /v3/keys` with
the admin JWT and a body limiting scope to the `openexec` workspace
(see Honcho's API docs); never put an admin JWT in
`openexec-api-prod`'s secrets. If a dev admin JWT leaks, rotate
`AUTH_JWT_SECRET` immediately (see "Rotate the JWT secret" below) —
that invalidates every issued token in one shot.

Set OE-side secrets:

```bash
flyctl secrets set -a openexec-api-dev \
    HONCHO_ENABLED=true \
    HONCHO_API_KEY=hch-... \
    HONCHO_BASE_URL=http://openexec-honcho-dev.flycast:8000 \
    HONCHO_WORKSPACE_ID=openexec
```

OE's wrapper picks up the new env on the next deploy or restart.

### 6. Smoke

```bash
# From inside openexec-api-dev:
flyctl ssh console -a openexec-api-dev \
    -C 'curl -sf -H "Authorization: Bearer $HONCHO_API_KEY" \
         http://openexec-honcho-dev.flycast:8000/v3/workspaces'
```

Then exercise an end-to-end turn from the UI (or a Slack/Discord DM as
a user with a matching `Person` row) and check the Honcho deriver logs
for processed messages:

```bash
flyctl logs -a openexec-honcho-dev | grep -i deriver
```

## Day-2 operations

### Inspect logs

```bash
flyctl logs -a openexec-honcho-dev                              # tail both processes
flyctl logs -a openexec-honcho-dev --process-group api          # api only
flyctl logs -a openexec-honcho-dev --process-group deriver      # deriver only
```

### Database backup

Fly Postgres takes automatic volume snapshots (retention varies by plan
— check the Fly dashboard for your cluster's current schedule). The
current `flyctl` does not expose a "create backup now" subcommand;
`flyctl postgres --help` only lists create/db/detach/events/failover/
import/list/renew-certs/restart/users. For an ad-hoc snapshot before a
risky change, take a `pg_dump`:

```bash
# Pull credentials the same way step 2 did — secrets aren't readable via
# `flyctl secrets list`, so we ssh into the api container and parse the
# already-aliased DB_CONNECTION_URI.
DB_URL=$(flyctl ssh console -a openexec-honcho-dev --process-group api \
    -C 'printenv DB_CONNECTION_URI' \
    | sed 's|^postgresql+psycopg://|postgres://|')   # pg_dump wants the bare scheme

# Proxy the cluster locally, then dump.
flyctl proxy 5432 -a openexec-honcho-pg &   # tunnels Fly PG to localhost:5432
PROXY_PID=$!
pg_dump "$DB_URL" > honcho-$(date +%Y%m%d).sql
kill $PROXY_PID
```

To restore, see Fly's PG runbook
([fly.io/docs/postgres/managing](https://fly.io/docs/postgres/managing/));
do not invent your own restore procedure here without testing on a
throwaway cluster first.

### Embedding quality ladder

The default deploy uses `BAAI/bge-small-en-v1.5` (384-dim, ~130MB)
served by the local `embed` process. On the MTEB English benchmark this
is roughly tied with OpenAI's `text-embedding-3-small`, but it's smaller
and English-only. If retrieval quality feels weak (use the quality
probe below to confirm), climb the ladder before reaching for a vendor
embedding API.

| Step | Model | Image+RAM delta | How to switch |
|---|---|---|---|
| Default | `BAAI/bge-small-en-v1.5` (384-dim) | baseline | shipped |
| 1 | `BAAI/bge-base-en-v1.5` (768-dim) | +300MB image, +400MB RAM | `flyctl secrets set -a openexec-honcho-dev EMBED_MODEL=BAAI/bge-base-en-v1.5` (then rebuild + redeploy — fastembed needs the model in its cache, which is baked at build time) |
| 2 | `BAAI/bge-large-en-v1.5` (1024-dim) | +1.2GB image, +1.2GB RAM | same pattern; bump the `embed` VM to 2GB in `fly.honcho.toml` first |
| 3 | OpenRouter `openai/text-embedding-3-small` (1536-dim) | network hop, ~$0.02/M tokens | `flyctl secrets set -a openexec-honcho-dev EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=https://openrouter.ai/api/v1 EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY="$OPENROUTER_API_KEY" EMBEDDING_VECTOR_DIMENSIONS=1536` AND change `[embedding.model_config].model` in `config.toml` to `openai/text-embedding-3-small`. The vector-dim change triggers `configure_embeddings.py --yes` (run by `release_command`) to ALTER the pgvector column from 384 to 1536 — destructive on existing embeddings; back up first. |

Step 3 reaches outside Fly's network for embeddings — only do it if
local models genuinely underperform. The OpenRouter cost on dev volume
is negligible (~$1-2/month) but the data-residency posture changes.

### Quality probe

The "is retrieval actually working" check, run once a week or before a
config bump:

1. Pick 5 turns from the past 7 days where a `Person` told the
   Executive something durable (preference, ongoing concern, factual
   claim). Note the message contents.
2. Ask each of those Persons (or simulate via a dev account that maps
   to a `Person` row) a follow-up that *references* the earlier fact
   without naming it directly. Example: original "I prefer terse
   bullet points"; probe "summarize Q3 for me — what level of detail
   do you want?"
3. Score each probe 0-2:
   - 2: peer_memory block clearly surfaced the relevant fact
   - 1: surfaced something tangentially related
   - 0: missed it entirely (irrelevant or empty block)
4. Average across the 5 probes. If &lt; 1.5, climb the embedding ladder.
   If &gt; 1.7, you can probably tier down (or stay put).

Capture results in a markdown table somewhere — the trend over time
matters more than any single score.

### Cost monitoring

Two cost meters to watch:

- **OpenRouter dashboard** — `LLM_OPENAI_API_KEY` (your OpenRouter key)
  drives every Honcho LLM call. Filter the OpenRouter usage view by the
  call pattern actually configured in `docker/honcho/config.toml`:
  **Haiku** for deriver / summary / dialectic minimal+low; **Sonnet**
  for dialectic medium+high+max and dream deduction. The biggest line
  items in practice are likely dreaming (continuous background, Sonnet)
  and the deriver (one Haiku call per inbound user message). Expect a
  few dollars per day on dev traffic — confirm with a week of real
  OpenRouter data before estimating prod-volume cost.
- **Fly billing** — three machines (api 1.5GB, deriver 2GB, embed 1GB)
  plus the Postgres cluster. Sticker for the dev cluster lands roughly
  $25-35/month on shared-cpu instances.

If OpenRouter spend spikes, the first knob to turn is dreaming
frequency / on-off. Honcho exposes `[dream].FREQUENCY_HOURS` and the
master switch `[dream].ENABLED`; setting `ENABLED=false` halts all
background spend within a deriver tick (~1s).

### Rotate the JWT secret

```bash
NEW_SECRET=$(openssl rand -hex 32)
flyctl secrets set -a openexec-honcho-dev AUTH_JWT_SECRET="$NEW_SECRET"
# Mint a new API key with the new secret (see step 5).
flyctl secrets set -a openexec-api-dev HONCHO_API_KEY=hch-new-...
```

Rotation invalidates all previously-issued tokens. OE's wrapper will
401 until both secrets are updated and the OE app restarts — schedule
the rotation accordingly.

### Bump Honcho version

```bash
# 1. Read the release notes — Honcho ships breaking schema changes
# between minors. https://github.com/plastic-labs/honcho/releases
#
# 2. Update the pin in docker/honcho/Dockerfile:
#       ARG HONCHO_VERSION=v3.0.7  →  v3.0.8 (or whatever)
#
# 3. Deploy. Fly's [deploy].release_command (configured in
# fly.honcho.toml) runs provision_db.py + configure_embeddings.py --yes
# automatically before new machines become active — no separate
# migration step needed. If the release_command fails the deploy
# aborts and the previous release stays serving.
flyctl deploy -c fly.honcho.toml

# 4. Smoke (step 6 above). Roll back via `flyctl releases rollback`
# AND `alembic downgrade` if needed.
```

Don't bump Honcho versions in the same PR as OE-side changes — keep
the upgrade isolated so a rollback is single-purpose.

### GitHub Actions deploy

`.github/workflows/deploy.yml` includes a `deploy-honcho` job that
auto-deploys on push to `main` whenever files under `docker/honcho/**`,
`fly.honcho.toml`, or the workflow itself change. Manual deploys are
also available via the workflow's `workflow_dispatch` trigger — pick
`honcho` as the target.

Schema migrations + the `configure_embeddings.py` ALTER run as Fly's
`[deploy].release_command` (configured in `fly.honcho.toml`) — a
one-shot machine that runs before new release machines become active.
The CI workflow itself doesn't SSH into the cluster; if the
release_command fails, the deploy aborts and the previous release
stays serving, so a bad migration never reaches user traffic.

**One-time setup the operator must do**:

1. Generate a Fly API token scoped to `openexec-honcho-dev`:
   ```bash
   flyctl tokens create deploy -a openexec-honcho-dev
   ```
2. In the GitHub repo settings → Secrets and variables → Actions, add
   a new repository secret `FLY_API_TOKEN_HONCHO` with the token value.

We use a separate per-app token (mirroring `FLY_API_TOKEN_API` /
`FLY_API_TOKEN_UI`) so a compromised CI token for the api/ui can't
also reach the memory app.

**Note**: the `"both"` choice in the `workflow_dispatch` target dropdown
intentionally does NOT include honcho — Honcho is a memory dep, not
part of the app pair, and we don't want a routine `api`/`ui` push to
cycle the deriver mid-thought. Bump Honcho explicitly.

### Kill switch

If Honcho is misbehaving (returning bad context, costing too much,
whatever), flip the OE-side flag without touching the Honcho app:

```bash
flyctl secrets set -a openexec-api-dev HONCHO_ENABLED=false
```

OE's wrapper no-ops immediately on the next turn. The Honcho app keeps
running but receives no traffic — fine for debugging without
double-rollout pressure.

## Graduating to prod

When the dev app proves out, the prod equivalent is the same recipe with
different names:

- `openexec-honcho-prod` app.
- `openexec-honcho-prod-pg` Postgres cluster (consider larger VM + larger
  volume; check pgvector index sizing first).
- Separate `HONCHO_API_KEY` (don't share dev's).
- Decide whether prod stays on the Haiku-cheap-tier / Sonnet-deep-tier
  split via OpenRouter (cheapest with what we already use) or
  diversifies the OpenRouter model slugs for the deriver tier (e.g.
  `google/gemini-2.5-flash` is meaningfully cheaper per token at
  comparable quality). Per-call routing through OpenRouter means
  swapping is a config-line change — no second vendor relationship.
- Add the prod app to OE's deploy automation (CI workflow + Makefile
  target).

A clean separation here matters: dev and prod must not share a Honcho
workspace, or a malformed test turn pollutes a real user's peer card.
