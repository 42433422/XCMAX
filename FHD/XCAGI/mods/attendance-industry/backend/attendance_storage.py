"""Owner-local policy and bounded temporary attendance workbooks."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.mod_sdk.attendance_artifacts import allocate_file
from app.mod_sdk.owner_workspace import owner_workspace
from resources.config.approval_config import normalize_attendance_policy

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
ARTIFACT_TTL_SECONDS = 24 * 60 * 60
_ARTIFACT = re.compile(r"attendance-(?:upload|output|export)-[0-9a-f]{32}\.(?:xlsx|xlsm|xls)\Z")


def read_policy(owner: str) -> dict:
    path = owner_workspace("attendance-industry", owner_id=owner).file_path("policy.json")
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError("invalid owner attendance policy")
    return normalize_attendance_policy(value)


def save_policy(owner: str, value: dict) -> dict:
    normalized = normalize_attendance_policy(value)
    workspace = owner_workspace("attendance-industry", owner_id=owner)
    workspace.root.mkdir(parents=True, exist_ok=True)
    target = workspace.file_path("policy.json")
    descriptor, temporary = tempfile.mkstemp(prefix=".policy-", dir=workspace.root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(normalized, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return normalized


def prune_expired(root: Path) -> None:
    cutoff = time.time() - ARTIFACT_TTL_SECONDS
    for path in root.iterdir():
        if _ARTIFACT.fullmatch(path.name) and not path.is_symlink():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass  # Another request already removed the expired artifact.


def _check_workbook(path: Path, suffix: str) -> None:
    if suffix == ".xls":
        with path.open("rb") as stream:
            if stream.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                raise HTTPException(400, "上传内容不是有效的 Excel 工作簿")
        return
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            expanded = sum(item.file_size for item in members)
            if len(members) > 1024 or expanded > MAX_EXPANDED_BYTES:
                raise HTTPException(413, "工作簿解压后超出大小限制")
            if any(item.file_size > 200 * max(1, item.compress_size) for item in members):
                raise HTTPException(413, "工作簿压缩比例超出限制")
            if "xl/workbook.xml" not in archive.namelist() or archive.testzip() is not None:
                raise HTTPException(400, "上传内容不是有效的 Excel 工作簿")
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError):
        raise HTTPException(400, "工作簿已损坏或加密") from None


async def save_upload(file: UploadFile, owner: str, suffix: str) -> Path:
    path = allocate_file(owner, "upload", suffix)
    accepted = False
    try:
        prune_expired(path.parent)
        size = 0
        with path.open("xb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "考勤文件不能超过 32 MiB")
                stream.write(chunk)
        _check_workbook(path, suffix)
        accepted = True
        return path
    finally:
        if not accepted:
            path.unlink(missing_ok=True)
        await file.close()
