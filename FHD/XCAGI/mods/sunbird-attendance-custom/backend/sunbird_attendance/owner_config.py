"""Customer conversion settings; never modify the host approval configuration."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from fastapi import HTTPException

from app.mod_sdk.owner_workspace import owner_workspace

from .policy import normalize_policy

MOD_ID = "sunbird-attendance-custom"
TEMPLATE_NAME = "attendance-template.xlsx"


def read_policy() -> dict[str, Any]:
    path = owner_workspace(MOD_ID).file_path("policy.json")
    if not path.is_file():
        return normalize_policy({})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(409, "当前账号的转换规则不可读取") from None
    if not isinstance(value, dict):
        raise HTTPException(409, "当前账号的转换规则无效")
    return normalize_policy(value)


def save_policy(value: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_policy(value)
    workspace = owner_workspace(MOD_ID)
    workspace.root.mkdir(parents=True, exist_ok=True)
    path = workspace.file_path("policy.json")
    descriptor, temporary = tempfile.mkstemp(prefix=".policy-", dir=workspace.root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(normalized, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        from pathlib import Path

        Path(temporary).unlink(missing_ok=True)
    return normalized
