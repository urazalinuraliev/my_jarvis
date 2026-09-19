"""OpenAI-compatible embeddings sidecar for Open Executive's Honcho deploy.

Honcho's deriver makes embedding calls through its `openai` transport. We
serve `BAAI/bge-small-en-v1.5` locally via fastembed (ONNX, no torch)
behind this thin shim so embeddings stay inside the Fly private network —
no third-party embedding vendor, no per-call cost.

Wire shape: Fly runs this as its own process group (`embed`); the deriver
process resolves it via `embed.process.openexec-honcho-dev.internal:8001`.
Honcho's `[embedding.model_config].base_url` points at that DNS.

The endpoint mirrors OpenAI's `/v1/embeddings` shape just enough that the
`AsyncOpenAI` client Honcho uses (`src/embedding_client.py:175`) gets a
response it can deserialise. `model` in the request is accepted but
ignored — we always use the model the container was built with.

Upgrade ladder is documented in `docs/honcho-hosting.md`: swap
`EMBED_MODEL` env var to `BAAI/bge-base-en-v1.5` / `bge-large-en-v1.5`
or flip `EMBEDDING_BASE_URL` on the Honcho app to OpenRouter, no code
change here.
"""
from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import FastAPI
from fastembed import TextEmbedding
from pydantic import BaseModel, Field

logger = logging.getLogger("embed_server")
logging.basicConfig(level=logging.INFO)

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_MODEL = os.environ.get("EMBED_MODEL", _DEFAULT_MODEL)

# Construct the embedder at import so the first request doesn't pay the
# model-load cost (the model itself is pre-downloaded by the Dockerfile).
logger.info("embed_server: loading model=%s", EMBED_MODEL)
_embedder = TextEmbedding(model_name=EMBED_MODEL)
logger.info("embed_server: model loaded")

app = FastAPI(title="openexec-honcho-embed", version="1.0.0")


class _EmbedRequest(BaseModel):
    """OpenAI-compatible request body.

    `input` can be a single string or list of strings per OpenAI's spec;
    we coerce to list-of-string and embed in one batch.
    `model` is accepted for SDK compatibility but ignored — the deployed
    model is fixed by EMBED_MODEL.
    """

    input: Annotated[str | list[str], Field(description="text(s) to embed")]
    model: str | None = None
    # Accepted for OpenAI-SDK compatibility but ignored — we always
    # return floats. Callers requesting "base64" will receive floats
    # anyway; if you need base64 support, add an encoder branch here.
    # Honcho's deriver doesn't request base64 so this hasn't bit yet.
    encoding_format: str | None = None


class _EmbedDatum(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class _EmbedUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class _EmbedResponse(BaseModel):
    object: str = "list"
    data: list[_EmbedDatum]
    model: str
    usage: _EmbedUsage


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe used by Fly's http_check."""
    return {"status": "ok", "model": EMBED_MODEL}


@app.post("/v1/embeddings", response_model=_EmbedResponse)
def embeddings(req: _EmbedRequest) -> _EmbedResponse:
    inputs = [req.input] if isinstance(req.input, str) else list(req.input)
    # fastembed returns numpy arrays; coerce to plain Python lists so the
    # JSON encoder doesn't have to know about numpy. Sync call — fastembed
    # is CPU-bound and not async; running it on the request thread is
    # fine for our throughput (deriver makes them serially per message).
    vectors = [vec.tolist() for vec in _embedder.embed(inputs)]
    return _EmbedResponse(
        data=[_EmbedDatum(index=i, embedding=vec) for i, vec in enumerate(vectors)],
        model=EMBED_MODEL,
        # fastembed doesn't surface token counts; report zeros. Honcho
        # doesn't bill on these — it only logs them.
        usage=_EmbedUsage(),
    )
