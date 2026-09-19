"""Unit tests for the shared attachments module.

All HTTP calls and filesystem operations are mocked — no network or disk I/O.
"""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.integrations.attachments import (
    AttachmentItem,
    _MAX_EXTRACTED_CHARS,
    build_attachment_output,
    download_bytes,
    process_attachments,
)


# --------------------------------------------------------------------------- #
# download_bytes
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_download_bytes_returns_content():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.content = b"hello world"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        data = await download_bytes("https://example.com/file.pdf")

    assert data == b"hello world"


@pytest.mark.asyncio
async def test_download_bytes_raises_on_content_length_exceeded():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"content-length": str(30 * 1024 * 1024)}  # 30 MB > 20 MB limit
    mock_resp.content = b"x"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="too large"):
            await download_bytes("https://example.com/big.pdf")


@pytest.mark.asyncio
async def test_download_bytes_raises_when_actual_content_exceeds_limit():
    """Content-Length header absent but actual payload is oversized."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.content = b"x" * (21 * 1024 * 1024)  # 21 MB

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="too large"):
            await download_bytes("https://example.com/big.pdf")


# --------------------------------------------------------------------------- #
# build_attachment_output — image routing
# --------------------------------------------------------------------------- #

def test_build_attachment_output_png_returns_image_block():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20  # fake PNG header
    extra_text, image_blocks = build_attachment_output("chart.png", data, "image/png")

    assert extra_text == ""
    assert len(image_blocks) == 1
    block = image_blocks[0]
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    assert block["source"]["data"] == base64.standard_b64encode(data).decode()


def test_build_attachment_output_jpeg_normalises_jpg_mime():
    """'image/jpg' (non-standard) must be normalised to 'image/jpeg'."""
    data = b"\xff\xd8\xff"  # JPEG magic bytes
    extra_text, image_blocks = build_attachment_output("photo.jpg", data, "image/jpg")

    assert extra_text == ""
    assert image_blocks[0]["source"]["media_type"] == "image/jpeg"


def test_build_attachment_output_image_no_content_type_infers_from_suffix():
    data = b"GIF89a"
    extra_text, image_blocks = build_attachment_output("anim.gif", data, "")

    assert extra_text == ""
    assert image_blocks[0]["source"]["media_type"] == "image/gif"


# --------------------------------------------------------------------------- #
# build_attachment_output — text document routing
# --------------------------------------------------------------------------- #

def test_build_attachment_output_pdf_extracts_text_and_schedules_ingest():
    extracted = "Quarterly revenue grew 23%."
    with (
        patch(
            "openexecutive.integrations.attachments._extract_text",
            return_value=extracted,
        ),
        patch("openexecutive.integrations.attachments._schedule_ingest") as mock_ingest,
    ):
        extra_text, image_blocks = build_attachment_output(
            "report.pdf", b"%PDF-fake", "application/pdf"
        )

    assert image_blocks == []
    assert "[Attached: report.pdf]" in extra_text
    assert "Quarterly revenue grew 23%." in extra_text
    mock_ingest.assert_called_once()


def test_build_attachment_output_truncates_long_text():
    # 10x the limit so the label overhead is negligible relative to the total.
    long_text = "word " * (_MAX_EXTRACTED_CHARS * 2)
    with (
        patch(
            "openexecutive.integrations.attachments._extract_text",
            return_value=long_text,
        ),
        patch("openexecutive.integrations.attachments._schedule_ingest"),
    ):
        extra_text, _ = build_attachment_output("doc.txt", b"...", "text/plain")

    assert "truncated" in extra_text.lower()
    # Total extra_text is label + capped text; must be much smaller than input.
    assert len(extra_text) < len(long_text) // 2


def test_build_attachment_output_empty_extraction_returns_notice():
    with patch(
        "openexecutive.integrations.attachments._extract_text",
        return_value="   ",
    ):
        extra_text, image_blocks = build_attachment_output("empty.pdf", b"", "application/pdf")

    assert image_blocks == []
    assert "could not extract" in extra_text.lower()


# --------------------------------------------------------------------------- #
# build_attachment_output — unsupported type
# --------------------------------------------------------------------------- #

def test_build_attachment_output_unsupported_type_returns_notice():
    extra_text, image_blocks = build_attachment_output(
        "model.xlsx", b"PK...", "application/vnd.ms-excel"
    )

    assert image_blocks == []
    assert "unsupported type" in extra_text.lower()
    assert "model.xlsx" in extra_text


# --------------------------------------------------------------------------- #
# process_attachments
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_process_attachments_skips_oversized_item():
    items = [
        AttachmentItem(
            url="https://example.com/big.pdf",
            filename="big.pdf",
            content_type="application/pdf",
            size=25 * 1024 * 1024,  # 25 MB > 20 MB limit
        )
    ]
    extra_text, image_blocks = await process_attachments(items)

    assert "too large" in extra_text.lower() or "skipped" in extra_text.lower()
    assert image_blocks == []


@pytest.mark.asyncio
async def test_process_attachments_skips_failed_download_and_continues():
    """A download error on item 1 must not stop item 2 from processing."""
    items = [
        AttachmentItem(url="https://fail.example.com/a.pdf", filename="a.pdf", content_type="application/pdf"),
        AttachmentItem(url="https://ok.example.com/b.png", filename="b.png", content_type="image/png"),
    ]

    async def _fake_download(url: str, headers=None, max_bytes=None):
        if "fail" in url:
            raise ConnectionError("network down")
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    with patch("openexecutive.integrations.attachments.download_bytes", side_effect=_fake_download):
        extra_text, image_blocks = await process_attachments(items)

    # Item 1 failed — note in text
    assert "a.pdf" in extra_text
    # Item 2 succeeded — got an image block
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_process_attachments_concatenates_multiple_texts():
    items = [
        AttachmentItem(url="https://example.com/a.txt", filename="a.txt", content_type="text/plain"),
        AttachmentItem(url="https://example.com/b.txt", filename="b.txt", content_type="text/plain"),
    ]

    async def _fake_download(url: str, headers=None, max_bytes=None):
        return b"content from " + url.encode().split(b"/")[-1]

    with (
        patch("openexecutive.integrations.attachments.download_bytes", side_effect=_fake_download),
        patch(
            "openexecutive.integrations.attachments._extract_text",
            side_effect=lambda data, filename: data.decode(),
        ),
        patch("openexecutive.integrations.attachments._schedule_ingest"),
    ):
        extra_text, image_blocks = await process_attachments(items)

    assert "a.txt" in extra_text
    assert "b.txt" in extra_text
    assert image_blocks == []
