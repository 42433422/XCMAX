"""Bounded upload reads with one explicit owner for closing every input."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from starlette.datastructures import UploadFile

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


async def read_workbench_uploads(files: Sequence[UploadFile]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        for upload in files or []:
            content = bytearray()
            while True:
                chunk = await upload.read(
                    min(READ_CHUNK_BYTES, MAX_UPLOAD_BYTES + 1 - len(content))
                )
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_UPLOAD_BYTES:
                    raise HTTPException(400, f"文件过大: {upload.filename}")
            result.append({"filename": upload.filename or "upload.bin", "content": bytes(content)})
        return result
    finally:
        for upload in files or []:
            await upload.close()
