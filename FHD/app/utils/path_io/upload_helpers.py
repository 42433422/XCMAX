"""Shared upload helpers for FastAPI routes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.utils.path_io.path_utils import get_upload_dir
from app.utils.security.secure_filename import secure_filename


async def save_upload_file(upload: UploadFile, *, subdir: str) -> str:
    """
    Persist an uploaded file under ``get_upload_dir()/subdir``.

    Returns the absolute path to the saved file.
    """
    if not upload.filename:
        raise ValueError("上传文件缺少文件名")
    body = await upload.read()
    return await run_in_threadpool(save_upload_bytes, body, subdir=subdir, filename=upload.filename)


def save_upload_bytes(content: bytes, *, subdir: str, filename: str) -> str:
    """Persist raw bytes to the upload directory."""
    safe_name = secure_filename(filename)
    upload_dir = Path(get_upload_dir()) / subdir
    upload_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = upload_dir / safe_name
    resolved_path.write_bytes(content)
    return str(resolved_path)


def _capability_upload_directory(context: dict[str, Any], namespace: str) -> Path:
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", namespace):
        raise ValueError("上传能力目录无效")
    actor = _bound_actor(context)
    mod = str((context.get("_mod_authorization") or {}).get("mod_id") or "")
    scope = "\0".join((str(actor.id), str(actor.tenant_id or ""), mod))
    owner = hashlib.sha256(scope.encode()).hexdigest()
    return Path(get_upload_dir()) / "capability-inputs" / namespace / owner


def read_capability_upload(
    params: dict[str, Any],
    context: dict[str, Any],
    *,
    namespace: str,
    suffixes: frozenset[str],
) -> bytes:
    """Read the original actor-owned input and check its frozen content digest."""
    from app.infrastructure.workspace import resolve_existing_file_under_root

    digest = str(params.get("sha256") or "")
    name = str(params.get("saved_name") or "")
    suffix = Path(name).suffix.lower()
    if (
        not re.fullmatch(r"[a-f0-9]{64}", digest)
        or suffix not in suffixes
        or name != digest + suffix
    ):
        raise PermissionError("上传文件回执无效")
    directory = _capability_upload_directory(context, namespace)
    root = Path(get_upload_dir())
    path = resolve_existing_file_under_root(root, str((directory / name).relative_to(root)))
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise PermissionError("上传文件与原始请求摘要不一致")
    return content


def stage_capability_upload(
    content: bytes,
    filename: str,
    context: dict[str, Any],
    *,
    namespace: str,
    suffixes: frozenset[str],
) -> dict[str, str]:
    """Retain one immutable source for the canonical task and all its retries."""
    suffix = Path(filename).suffix.lower()
    if suffix not in suffixes or not content:
        raise ValueError("上传文件为空或类型不受支持")
    digest = hashlib.sha256(content).hexdigest()
    params = {"saved_name": digest + suffix, "sha256": digest}
    directory = _capability_upload_directory(context, namespace)
    root = Path(get_upload_dir())
    for component in (directory, *directory.parents):
        if component.is_symlink():
            raise PermissionError("上传目录无效")
        if component == root:
            break
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with (directory / params["saved_name"]).open("xb") as target:
            target.write(content)
    except FileExistsError:
        # A transport retry uses exactly the original name and business input.
        read_capability_upload(params, context, namespace=namespace, suffixes=suffixes)
    return params
