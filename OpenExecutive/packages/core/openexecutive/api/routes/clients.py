"""FastAPI routes for client-company slots (fractional / multi-client mode).

Mirrors the shape of ``api.routes.fixtures`` — thin handlers over
``openexecutive.clients.slots``, which owns validation, the shared
destructive-op lock, and the save/restore machinery. Single-company installs
simply see an empty list here; nothing in the default experience changes
until a slot is explicitly created.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

router = APIRouter()

# Intake attachments accepted alongside pasted notes on POST /clients/generate.
# Extensions whose text knowledge.loader.extract_text_from_file can read (legacy
# binary .xls is excluded — openpyxl reads only .xlsx/.xlsm).
INTAKE_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".md",
    ".txt",
}
_INTAKE_MAX_BYTES_PER_FILE = 25 * 1024 * 1024  # 25 MB
_INTAKE_MAX_FILES = 8
# Per-file cap on the text fed into the LLM draft (bounds cost/context); the
# fuller extracted text (up to _INTAKE_MAX_DOC_CHARS) is still stored as a doc.
_INTAKE_GEN_CHARS_PER_FILE = 15_000
_INTAKE_MAX_DOC_CHARS = 40_000


class CreateClientRequest(BaseModel):
    display_name: str = Field(..., max_length=200)
    slug: str | None = Field(default=None, max_length=64)
    # "current" captures the live company into the new slot (and activates it);
    # "blank" creates an empty client to onboard fresh; "generated" writes a
    # seed slot from an engagement-intake bundle (see POST /clients/generate).
    source: str = "current"
    bundle: dict | None = None
    intake_description: str = Field(default="", max_length=20000)


class ClientMetaPatch(BaseModel):
    """Engagement metadata patch — practice-level fields on a slot's meta.json.

    All optional; only provided fields are written. The slot module enforces
    the allowlist and status enum (so direct callers get the same gate).
    """

    role: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=32)
    engagement_start: str | None = Field(default=None, max_length=32)
    renewal_date: str | None = Field(default=None, max_length=32)
    retainer: str | None = Field(default=None, max_length=200)
    hours_per_week: float | None = None
    primary_contact: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


def _raise_for(exc: Exception) -> None:
    from openexecutive.clients.slots import (
        ClientSlotConflictError,
        ClientSlotNotFoundError,
    )

    if isinstance(exc, ClientSlotNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ClientSlotConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/clients")
async def list_clients() -> dict:
    from openexecutive.cli.fixture_loader import get_fixture_status
    from openexecutive.clients.rotation import rotation_in_progress
    from openexecutive.clients.slots import get_active_client, list_client_slots
    from openexecutive.config import get_settings

    settings = get_settings()
    status = get_fixture_status(settings)
    return {
        "active": get_active_client(settings),
        "fixture_active": status.get("active_fixture"),
        "rotation_in_progress": rotation_in_progress(settings),
        "clients": list_client_slots(settings),
    }


@router.post("/clients")
async def create_client(req: CreateClientRequest) -> dict:
    from openexecutive.clients.slots import ClientSlotError, create_client_slot
    from openexecutive.config import get_settings

    try:
        return await create_client_slot(
            get_settings(),
            display_name=req.display_name,
            slug=req.slug,
            source=req.source,
            bundle=req.bundle,
            intake_description=req.intake_description,
        )
    except ClientSlotError as exc:
        _raise_for(exc)
        raise  # unreachable — _raise_for always raises


def _extract_intake_upload(filename: str, content: bytes) -> tuple[str, str]:
    """Validate one intake upload and return ``(safe_filename, extracted_text)``.

    Raises ``HTTPException(400)`` for a bad name/extension and ``413`` when the
    file exceeds the per-file size cap. The text is extracted by the same
    ``knowledge.loader`` path the /documents upload uses, via a temp file.
    """
    from openexecutive.knowledge.loader import extract_text_from_file

    safe = Path(filename or "").name
    if not safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    ext = Path(safe).suffix.lower()
    if ext not in INTAKE_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {ext}. "
                f"Allowed: {', '.join(sorted(INTAKE_ALLOWED_EXTENSIONS))}"
            ),
        )
    if len(content) > _INTAKE_MAX_BYTES_PER_FILE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{safe}: file too large "
                f"(limit {_INTAKE_MAX_BYTES_PER_FILE // (1024 * 1024)} MB)"
            ),
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        text = extract_text_from_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return safe, text.strip()


async def _gather_intake_attachments(
    uploads: list[UploadFile],
) -> list[tuple[str, str]]:
    """Read, validate, and extract text from intake uploads.

    Enforces the per-request file-count cap, then returns ``(safe_filename,
    extracted_text)`` for each attachment that yielded text. Files with no
    extractable text (e.g. a scanned, image-only PDF) are dropped silently;
    per-file type/size validation (and its 400/413 errors) lives in
    ``_extract_intake_upload``.
    """
    if len(uploads) > _INTAKE_MAX_FILES:
        raise HTTPException(
            status_code=400, detail=f"Too many files (limit {_INTAKE_MAX_FILES})"
        )
    extracted: list[tuple[str, str]] = []
    for upload in uploads:
        if not upload.filename:
            continue
        # Read at most cap+1 bytes so an oversized part is rejected by
        # _extract_intake_upload (413) without buffering the whole stream.
        content = await upload.read(_INTAKE_MAX_BYTES_PER_FILE + 1)
        if not content:
            continue
        safe, text = _extract_intake_upload(upload.filename, content)
        if text:
            extracted.append((safe, text))
    return extracted


@router.post("/clients/generate")
async def generate_client(
    description: str = Form(""),
    files: list[UploadFile] = File(  # noqa: B008 — FastAPI multipart marker, mirrors chat.py
        default=[]
    ),
) -> dict:
    """Draft a client company from real intake notes and/or attached files.

    Accepts pasted intake material as ``description`` plus optional attachments
    (PDF/Word/Excel/CSV/Markdown/text). Each attachment's extracted text both
    (a) feeds the grounded engagement-intake draft and (b) is appended to the
    returned bundle's ``docs`` as ``source_<name>.md`` so it persists into the
    client slot and is indexed into the ``company_docs`` collection on
    activation. Nothing is persisted here — the UI posts the (possibly edited)
    bundle back to ``POST /clients`` with ``source="generated"``.
    """
    from openexecutive.clients.slots import derive_client_slug
    from openexecutive.config import get_settings
    from openexecutive.fixtures.generator import (
        DocSpec,
        GenerationError,
        _safe_doc_filename,
        generate_engagement_bundle,
    )

    notes = (description or "").strip()
    extracted = await _gather_intake_attachments(files or [])
    if not notes and not extracted:
        raise HTTPException(
            status_code=400,
            detail="description or at least one readable file is required",
        )

    # Material fed to the LLM: pasted notes + a capped block per attachment.
    parts = [notes] if notes else []
    parts += [
        f"=== Attached: {safe} ===\n{text[:_INTAKE_GEN_CHARS_PER_FILE]}"
        for safe, text in extracted
    ]
    combined = "\n\n".join(parts)

    settings = get_settings()
    try:
        bundle = await generate_engagement_bundle(combined, settings)
    except GenerationError as exc:
        # 422 — the model produced something unusable; surface it to the UI.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Persist each attachment's text as a company doc in the bundle so it flows
    # into the slot and is indexed on activation. Names are sanitized with the
    # same helper the persistence path uses and de-duplicated here (against the
    # LLM-written docs and each other) so the reviewed draft and the saved slot
    # show identical filenames — two files with the same stem don't collide.
    seen = {d.filename for d in bundle.docs}
    for i, (safe, text) in enumerate(extracted):
        stem = Path(safe).stem or "attachment"
        fn = _safe_doc_filename(f"source_{stem}", i)
        base = fn[:-3]  # strip the guaranteed ".md" suffix
        n = 2
        while fn in seen:
            fn = f"{base}_{n}.md"
            n += 1
        seen.add(fn)
        bundle.docs.append(DocSpec(filename=fn, content=text[:_INTAKE_MAX_DOC_CHARS]))

    return {
        "suggested_name": derive_client_slug(bundle.profile.name, settings),
        "display_name": bundle.profile.name,
        "bundle": bundle.model_dump(),
    }


@router.post("/clients/save")
async def save_client() -> dict:
    """Checkpoint the active client's live state into its slot."""
    from openexecutive.clients.slots import ClientSlotError, save_active_client
    from openexecutive.config import get_settings

    try:
        return await save_active_client(get_settings())
    except ClientSlotError as exc:
        _raise_for(exc)
        raise


@router.post("/clients/{slug}/activate")
async def activate_client(slug: str, request: Request) -> dict:
    """Switch the live company context to this client (saving the current one)."""
    from openexecutive.clients.slots import ClientSlotError, activate_client_slot
    from openexecutive.config import get_settings

    try:
        return await activate_client_slot(
            get_settings(), slug, app_state=request.app.state
        )
    except ClientSlotError as exc:
        _raise_for(exc)
        raise


@router.get("/clients/cockpit")
async def clients_cockpit() -> dict:
    """Practice-wide board: one rollup card per client (active first).

    Read-only across live DB + parked slot snapshots; one broken slot
    degrades to an error-flagged card rather than failing the board.
    """
    from datetime import UTC, datetime

    from openexecutive.clients.cockpit import practice_overview
    from openexecutive.config import get_settings

    cards = practice_overview(get_settings())
    return {
        "clients": [c.model_dump() for c in cards],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.patch("/clients/{slug}")
async def patch_client_meta(slug: str, req: ClientMetaPatch) -> dict:
    """Update a slot's engagement metadata (role, status, renewal, …)."""
    from openexecutive.clients.slots import ClientSlotError, update_client_meta
    from openexecutive.config import get_settings

    patch = req.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="empty metadata patch")
    try:
        return await update_client_meta(get_settings(), slug, patch)
    except ClientSlotError as exc:
        _raise_for(exc)
        raise


@router.delete("/clients/{slug}")
async def delete_client(slug: str) -> dict:
    from openexecutive.clients.slots import ClientSlotError, delete_client_slot
    from openexecutive.config import get_settings

    try:
        return await delete_client_slot(get_settings(), slug)
    except ClientSlotError as exc:
        _raise_for(exc)
        raise
