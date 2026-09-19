from __future__ import annotations

import asyncio
import hmac
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from openexecutive.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
# Telegram's 4096 limit is in UTF-16 code units; emoji count double.
# Use 2000 chars as a conservative safe limit.
_MAX_MSG_LEN = 2000

# Module-level client — reused across requests to avoid per-call TLS handshakes.
_http_client: httpx.AsyncClient | None = None

# Per-chat lock so two messages from the same chat serialize — without this,
# concurrent handlers both load stale history and write interleaved turns.
_chat_locks: dict[int, asyncio.Lock] = {}


def _chat_lock(chat_id: int) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30)
    return _http_client


def _tg_url(token: str, method: str) -> str:
    return _TELEGRAM_API.format(token=token, method=method)


def _split_message(text: str) -> list[str]:
    """Split a long response into ≤_MAX_MSG_LEN-char chunks on paragraph boundaries."""
    if len(text) <= _MAX_MSG_LEN:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= _MAX_MSG_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, _MAX_MSG_LEN)
        if split_at <= 0:
            split_at = text.rfind("\n", 0, _MAX_MSG_LEN)
        if split_at <= 0:
            split_at = _MAX_MSG_LEN
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remainder = text[split_at:].strip()
        if remainder == text:
            # No progress — force a hard split to avoid infinite loop.
            chunks.append(text[:_MAX_MSG_LEN])
            text = text[_MAX_MSG_LEN:]
        else:
            text = remainder
    return [c for c in chunks if c]


async def send_message(
    token: str,
    chat_id: int,
    text: str,
    parse_mode: str | None = None,
) -> str | None:
    """Send one or more messages to a Telegram chat, splitting if needed.

    ``parse_mode`` ("Markdown" | "HTML" | None) is forwarded to the Telegram
    API so callers can render bold/italic/bullet content. Default None keeps
    the existing plain-text behaviour for all current callers.

    Returns the Telegram message_id of the last chunk sent (best-effort —
    ``None`` if no chunk delivered or the response lacks one), so callers can
    link an outbound DM to a later reply. Existing callers ignore the return.
    """
    client = _get_http_client()
    last_message_id: str | None = None
    for chunk in _split_message(text):
        if not chunk:
            continue
        payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        resp = await client.post(
            _tg_url(token, "sendMessage"),
            json=payload,
        )
        if resp.is_error:
            logger.error(
                "Telegram sendMessage failed: %s %s", resp.status_code, resp.text
            )
            continue
        try:
            mid = resp.json().get("result", {}).get("message_id")
            if mid is not None:
                last_message_id = str(mid)
        except (ValueError, TypeError, AttributeError):
            pass
    return last_message_id


async def _get_telegram_file_bytes(token: str, file_id: str) -> tuple[str, bytes]:
    """Resolve a Telegram file_id to a download URL and fetch the bytes.

    Returns ``(file_path_on_tg_servers, data)``.  Raises on any error so the
    caller can skip the attachment and log it.
    """
    from openexecutive.integrations.attachments import download_bytes

    client = _get_http_client()
    resp = await client.get(_tg_url(token, f"getFile?file_id={file_id}"))
    resp.raise_for_status()
    result = resp.json().get("result", {})
    file_path = result.get("file_path", "")
    if not file_path:
        raise ValueError(f"Telegram getFile returned no file_path for file_id={file_id}")

    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    data = await download_bytes(url)
    return file_path, data


async def _run_crew_and_report(
    *,
    task: str,
    context: str,
    chat_id: int,
    token: str,
    sender_name: str,
    message_id: int,
) -> None:
    """Run the CrewAI Instagram crew asynchronously and deliver the Markdown report.

    Invoked as a background task from the webhook so the Telegram webhook
    never blocks. Uses the per-chat lock for deduplication (a second
    /strategy while one is running waits for the first to finish rather
    than spawning a duplicate pipeline). Errors are caught and surfaced
    as a clear user-facing notification instead of a silent drop.
    """
    session_id = f"telegram:{chat_id}"
    from openexecutive.audit import log_event as audit_log

    audit_log(
        "tool_invocation",
        f"CrewAI instagram crew triggered by {sender_name} (chat_id={chat_id}): {task[:160]}",
        actor="telegram",
        session_id=session_id,
        details={
            "channel": "telegram",
            "chat_id": chat_id,
            "message_id": message_id,
            "sender": sender_name,
            "crew": "instagram",
            "task": task,
        },
    )

    # Per-chat dedup: serialize crew runs from the same chat. Without this,
    # two near-simultaneous /strategy commands would both load the same
    # state and both fire full multi-agent pipelines — doubling cost and
    # delivering duplicate reports. Mirrors the lock used for regular
    # chat turns below.
    async with _chat_lock(chat_id):
        try:
            from openexecutive.integrations.crewai_adapter import get_crewai_adapter

            adapter = get_crewai_adapter(crew="instagram")
            result = await adapter.run(task=task, context=context)
        except Exception as exc:
            logger.exception(
                "Telegram: CrewAI instagram crew failed for chat_id=%s", chat_id
            )
            try:
                await send_message(
                    token,
                    chat_id,
                    "⚠️ The Instagram content crew hit an error and couldn't "
                    "complete. Please try again in a moment, or run "
                    "`openexecutive crew --crew instagram --task ...` from the "
                    "terminal for full error output.",
                )
            except Exception:
                logger.exception("Telegram: also failed to send crew error reply")
            return

        # Format the report as Telegram Markdown. CrewAI output is plain
        # text; we escape nothing (the crew's text is our own generated
        # content, not user data) and pass parse_mode="Markdown" so the
        # headline/bullet structure renders. Telegram's Markdown subset
        # doesn't support nested bold-italic or tables, so we keep the
        # formatting simple: bold headings + bullet lists.
        report = _format_crew_report(result, task=task)
        try:
            await send_message(token, chat_id, report, parse_mode="Markdown")
        except Exception:
            logger.exception(
                "Telegram: failed to deliver CrewAI report for chat_id=%s", chat_id
            )
            try:
                await send_message(
                    token,
                    chat_id,
                    "The crew finished but I couldn't deliver the report. "
                    "Please run `openexecutive crew --crew instagram --task ...` "
                    "from the terminal to see the output.",
                )
            except Exception:
                logger.exception("Telegram: also failed to send delivery-failure reply")


def _format_crew_report(result, *, task: str) -> str:
    """Render a CrewAI AgentResult as a Telegram Markdown report."""
    lines: list[str] = []
    lines.append(f"*Instagram Content Crew* — topic: {task}")
    lines.append("")

    if result.text:
        # CrewAI kickoff() returns a CrewOutput whose str() includes a
        # "Final Output" header + the raw agent prose. Trim that wrapper
        # so we control the rendering ourselves.
        text = result.text
        marker = "Final Output"
        idx = text.find(marker)
        if idx != -1:
            text = text[idx + len(marker) :].lstrip(": \n")
        lines.append(text.strip())
        lines.append("")

    if result.artifacts:
        lines.append("*Artifacts produced:*")
        for art in result.artifacts:
            name = art.get("name", "artifact")
            path = art.get("path", "")
            line = f"- `{name}`"
            if path:
                line += f" → `{path}`"
            lines.append(line)
        lines.append("")

    if result.consulted_specialists:
        lines.append(
            "_Specialists consulted: " + ", ".join(result.consulted_specialists) + "_"
        )

    return "\n".join(lines)


async def _process_and_reply(
    message_text: str,
    sender_name: str,
    chat_id: int,
    message_id: int,
    token: str,
    attachment_file_ids: list[tuple[str, str, str]] | None = None,
) -> None:
    """Handle one inbound Telegram message.

    ``attachment_file_ids`` is a list of ``(file_id, filename, content_type)``
    tuples for any files or photos attached to the message.
    """
    # Deterministic per-chat session id — stamped on every audit row (inbound,
    # chat_turn, specialist_consult, tool_invocation) so a single request can
    # be followed end-to-end in /audit. Must match the value used when the
    # Session is constructed below.
    session_id = f"telegram:{chat_id}"

    from openexecutive.audit import log_event as audit_log
    audit_log(
        "integration_inbound",
        f"Inbound telegram from {sender_name} (chat_id={chat_id}): {message_text[:160]}",
        actor="telegram",
        session_id=session_id,
        details={
            "channel": "telegram",
            "chat_id": chat_id,
            "message_id": message_id,
            "sender": sender_name,
            "text_len": len(message_text),
        },
    )
    # WaitForHuman inbound resolver — check BEFORE alert triage.
    try:
        from openexecutive.people.store import find_person_by_telegram_chat_id
        from openexecutive.workflows.inbound_resolver import resolve_inbound_message
        from openexecutive.workflows.resumer import apply_resolution

        person = find_person_by_telegram_chat_id(str(chat_id))
        if person is not None and person.id is not None:
            resolution = await resolve_inbound_message(
                channel="telegram",
                channel_ref=str(chat_id),
                from_person_id=person.id,
                text=message_text,
                message_id=str(message_id),
                in_reply_to="",
            )
            if resolution is not None and resolution.run_id:
                success = await apply_resolution(resolution.run_id, resolution)
                if success:
                    await send_message(token, chat_id, "Got it — your response has been recorded.")
                    return
    except Exception:
        logger.exception("Telegram: inbound resolver check failed")

    # Fork into alert triage pipeline (fire-and-forget, same pattern as other integrations).
    try:
        from openexecutive.alerts.models import AlertEvent
        from openexecutive.alerts.pipeline import schedule_evaluation

        schedule_evaluation(
            AlertEvent(
                source="telegram",
                external_id=str(message_id),
                body=message_text,
                user=sender_name,
            )
        )
    except Exception:
        logger.exception("Telegram: failed to schedule alert evaluation")

    # Process file / photo attachments before entering the chat lock so that
    # slow downloads don't hold the lock while the chat serialises.
    att_image_blocks: list[dict] = []
    if attachment_file_ids:
        try:
            from openexecutive.integrations.attachments import build_attachment_output

            for file_id, filename, content_type in attachment_file_ids:
                try:
                    _file_path, data = await _get_telegram_file_bytes(token, file_id)
                    # build_attachment_output works on bytes directly — we
                    # don't need AttachmentItem/process_attachments here since
                    # Telegram requires a separate getFile API call rather than
                    # a direct URL download.
                    att_text, img_blocks = build_attachment_output(filename, data, content_type)
                    if att_text:
                        message_text = (
                            f"{att_text}\n\n{message_text}" if message_text else att_text
                        )
                    att_image_blocks.extend(img_blocks)
                except Exception:
                    logger.exception(
                        "Telegram: failed to download/process attachment file_id=%s", file_id
                    )
        except Exception:
            logger.exception("Telegram: attachment processing setup failed")

    from openexecutive.knowledge.retriever import retrieve
    from openexecutive.memory.episodic import format_for_prompt
    from openexecutive.memory.session_store import (
        create_session,
        load_messages,
        save_message,
        update_session_timestamp,
    )
    from openexecutive.onboarding.profile_builder import load_or_create_profile
    from openexecutive.orchestrator.executive import Executive
    from openexecutive.orchestrator.mcp_gateway import get_active_gateway
    from openexecutive.orchestrator.session import Session

    response: str | None = None
    async with _chat_lock(chat_id):
        try:
            profile = load_or_create_profile()
            session = Session(
                session_id=session_id,
                company_profile=profile if not profile.is_empty() else None,
            )
            history = load_messages(session_id)
            if history:
                session.conversation_history = history
            # Record this channel_ref as user-initiated so the Executive may
            # schedule follow-ups back to this chat.
            session.seen_channel_refs.add(("telegram", str(chat_id)))
            retrieved_context = retrieve(query=message_text)
            episodic_context = format_for_prompt(session_id=session_id)

            # Look up the OE Person record so Honcho can key per-person
            # memory off Person.id (shared across channels). No match →
            # person_id stays None and the Honcho layer no-ops.
            from openexecutive.people.store import find_person_by_telegram_chat_id
            person = find_person_by_telegram_chat_id(str(chat_id))
            person_id = person.id if person else None

            # Hydrate with the context of any recent outbound DM oe sent this
            # chat, so a reply oe solicited from another session lands with its
            # backstory. Injected into the model's copy only — message_text is
            # persisted to history below and must stay free of the one-shot
            # block. One-shot consumed inside the helper.
            #
            # Gated to 1:1 private chats (positive chat_id; Telegram groups and
            # channels are negative) so private outbound context can never be
            # pulled into a group — mirrors the Discord is_dm / Slack mode=="dm"
            # guards.
            chat_user_message = message_text
            if chat_id > 0:
                from openexecutive.integrations.inbound_hydration import (
                    hydrate_user_message,
                )

                chat_user_message = hydrate_user_message(
                    channel="telegram",
                    channel_ref=str(chat_id),
                    user_message=message_text,
                )

            response = await Executive(mcp_gateway=get_active_gateway()).chat(
                user_message=chat_user_message,
                session=session,
                retrieved_context=retrieved_context,
                episodic_context=episodic_context,
                attachment_blocks=att_image_blocks or None,
                person_id=person_id,
            )
            await send_message(token, chat_id, response)
        except Exception:
            logger.exception("Telegram: handler error for message %s", message_id)
            try:
                await send_message(
                    token,
                    chat_id,
                    "I encountered an error processing your request. Please try again.",
                )
            except Exception:
                logger.exception("Telegram: also failed to send error reply")
            return

        # Persist only after a successful reply. Failures here must not trigger
        # a user-facing error — the user already got their answer.
        #
        # Channel sessions are owned by the resolved sender if mapped to a
        # Person, otherwise fall back to the principal so unrostered channel
        # threads still appear in the operator's sidebar (instead of becoming
        # invisible NULL-owner rows).
        from openexecutive.people.store import find_principal_person
        session_owner_id = person_id
        if session_owner_id is None:
            principal = find_principal_person()
            session_owner_id = principal.id if principal is not None else None
        try:
            create_session(
                session_id,
                f"Telegram {sender_name}",
                session.created_at.isoformat(),
                caller_person_id=session_owner_id,
            )
            save_message(session_id, "user", message_text)
            save_message(session_id, "assistant", response)
            update_session_timestamp(session_id)
        except Exception:
            logger.exception(
                "Telegram: failed to persist turn for session %s", session_id
            )


# Known bot commands that should be stripped before passing to the Executive.
# /strategy and /marketing are intercepted separately (see _crew_command_match)
# and dispatched to the CrewAI Instagram crew — they never reach the Executive.
_COMMAND_RE = re.compile(r"^/(start|help|ask)(?:@\w+)?\s*", re.IGNORECASE)

# Telegram commands that fan out to the integrated CrewAI Instagram crew.
# Matched BEFORE _COMMAND_RE stripping so the task text is preserved verbatim.
_CREW_COMMAND_RE = re.compile(
    r"^/(strategy|marketing)(?:@\w+)?\s*(?P<task>.*)",
    re.IGNORECASE,
)

# CrewAI runs can take a long time (multi-agent pipeline + LLM calls). Telegram
# silently drops webhook requests that exceed 5s with no ack, so we always
# return 200 immediately and do the real work in background_tasks. This ack
# message is sent synchronously inside the webhook so the user sees "on it"
# before the long poll.
_CREW_ACK_TEXT = (
    "🚀 Running the Instagram content crew for you — this runs a multi-agent "
    "pipeline (research → strategy → visuals → copywriting) and takes a couple "
    "of minutes. I'll post the final report here when it's done."
)


@router.post("/webhook/telegram", status_code=200)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="Telegram integration not configured")

    # Verify the secret token Telegram sends in the header (set when registering the webhook).
    if settings.telegram_webhook_secret:
        sent = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(sent, settings.telegram_webhook_secret):
            logger.warning("Telegram: webhook secret mismatch")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Parse body — return 200 on failure so Telegram doesn't retry bad payloads.
    try:
        body = await request.json()
    except Exception:
        logger.warning("Telegram: failed to parse JSON body")
        return {}

    # Only handle regular messages (ignore channel posts, edited messages, etc.)
    message = body.get("message")
    if not message:
        return {}

    # Extract fields safely — malformed payloads return 200 to stop Telegram retries.
    try:
        chat_id: int = message["chat"]["id"]
        message_id: int = message["message_id"]
    except (KeyError, TypeError):
        logger.warning("Telegram: malformed message payload, missing chat.id or message_id")
        return {}

    from_user: dict[str, Any] = message.get("from") or {}
    sender_name = " ".join(
        filter(None, [from_user.get("first_name"), from_user.get("last_name")])
    ) or from_user.get("username") or f"chat:{chat_id}"

    # Roster gate. The Telegram chat must match a non-archived Person
    # with telegram_chat_id set. Manage access via the /people UI; the
    # old TELEGRAM_ALLOWED_CHAT_IDS env var has been removed.
    from openexecutive.audit import log_event as audit_log
    from openexecutive.people.store import find_person_by_telegram_chat_id

    if find_person_by_telegram_chat_id(str(chat_id)) is None:
        logger.warning(
            "Telegram: rejected message from chat_id=%s (not in People roster)",
            chat_id,
        )
        audit_log(
            "integration_inbound",
            f"Rejected: telegram chat_id={chat_id} not in People roster",
            actor="telegram",
            details={
                "channel": "telegram",
                "chat_id": chat_id,
                "outcome": "rejected_unknown_sender",
            },
        )
        return {}

    text: str = message.get("text", "") or message.get("caption", "")
    text = text.strip()

    # CrewAI commands (/strategy, /marketing) fan out to the Instagram crew
    # instead of the Executive. Match BEFORE _COMMAND_RE stripping so the
    # task text is preserved verbatim.
    crew_match = _CREW_COMMAND_RE.match(text)
    if crew_match is not None:
        task = (crew_match.group("task") or "").strip()
        if not task:
            await send_message(
                token,
                chat_id,
                "Please tell me what topic to research. Example: "
                "`/strategy summer campaign for our new product launch`",
            )
            return {}
        background_tasks.add_task(
            _run_crew_and_report,
            task=task,
            context="",
            chat_id=chat_id,
            token=token,
            sender_name=sender_name,
            message_id=message_id,
        )
        # Acknowledge immediately so the user sees the crew is running
        # while Telegram waits. The real report lands as a follow-up
        # message once the multi-agent pipeline finishes.
        try:
            await send_message(token, chat_id, _CREW_ACK_TEXT)
        except Exception:
            logger.exception("Telegram: failed to send crew ack for chat_id=%s", chat_id)
        return {}

    # Only strip known bot commands (/start, /help, /ask), not arbitrary slash-prefixed content.
    text = _COMMAND_RE.sub("", text).strip()

    # Collect attachment metadata (file_id, filename, content_type).
    # Downloads happen inside _process_and_reply so this handler stays fast.
    attachment_file_ids: list[tuple[str, str, str]] = []

    # Single document (any file type).
    doc = message.get("document")
    if doc:
        file_id = doc.get("file_id", "")
        filename = doc.get("file_name") or f"file_{file_id}"
        content_type = doc.get("mime_type") or ""
        if file_id:
            attachment_file_ids.append((file_id, filename, content_type))

    # Photos — Telegram sends an array of sizes; pick the largest.
    photos = message.get("photo")
    if photos and isinstance(photos, list) and photos:
        largest = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = largest.get("file_id", "")
        if file_id:
            attachment_file_ids.append((file_id, f"photo_{file_id}.jpg", "image/jpeg"))

    # Require either text or at least one attachment to proceed.
    if not text and not attachment_file_ids:
        return {}

    background_tasks.add_task(
        _process_and_reply,
        message_text=text,
        sender_name=sender_name,
        chat_id=chat_id,
        message_id=message_id,
        token=settings.telegram_bot_token,
        attachment_file_ids=attachment_file_ids or None,
    )
    return {}
