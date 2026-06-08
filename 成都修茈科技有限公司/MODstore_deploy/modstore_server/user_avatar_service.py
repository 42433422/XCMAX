"""用户头像：存于 MODSTORE_DATA_DIR/user_avatars/{user_id}/。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException

AVATAR_MAX_BYTES = 2 * 1024 * 1024
_ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def avatar_data_root() -> Path:
    raw = (os.environ.get("MODSTORE_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data").resolve()


def avatar_public_url(version: int) -> str:
    v = max(0, int(version or 0))
    return f"/api/auth/avatar/file?v={v}"


def avatar_path_column(user) -> str:
    return (getattr(user, "avatar_path", None) or "").strip()


def avatar_version_column(user) -> int:
    return max(0, int(getattr(user, "avatar_version", 0) or 0))


def public_avatar_url_for_user(user) -> Optional[str]:
    if not avatar_path_column(user):
        return None
    return avatar_public_url(avatar_version_column(user))


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(
            400,
            f"仅支持 JPG/PNG/WebP/GIF，当前扩展名：{suffix or '(无)'}",
        )
    return suffix


def _storage_relpath(user_id: int, suffix: str) -> str:
    return f"user_avatars/{int(user_id)}/avatar{suffix}"


def resolve_avatar_file(relpath: str) -> Path:
    rel = (relpath or "").strip().replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(400, "无效头像路径")
    if not re.match(r"^user_avatars/\d+/avatar\.(jpe?g|png|webp|gif)$", rel, re.I):
        raise HTTPException(400, "无效头像路径")
    root = avatar_data_root()
    path = (root / rel).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(400, "无效头像路径")
    return path


def save_user_avatar(user_id: int, payload: bytes, filename: str) -> Tuple[str, str]:
    if len(payload) > AVATAR_MAX_BYTES:
        mb = max(1, AVATAR_MAX_BYTES // (1024 * 1024))
        raise HTTPException(413, f"头像过大（上限 {mb}MB）")
    if len(payload) < 16:
        raise HTTPException(400, "图片文件过小或已损坏")
    suffix = _safe_suffix(filename)
    relpath = _storage_relpath(user_id, suffix)
    dest = resolve_avatar_file(relpath)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob("avatar.*"):
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    try:
        dest.write_bytes(payload)
    except OSError as e:
        raise HTTPException(500, "写入头像失败") from e
    mime = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    return relpath, mime


def delete_user_avatar_files(user_id: int) -> None:
    folder = avatar_data_root() / "user_avatars" / str(int(user_id))
    if not folder.is_dir():
        return
    for p in folder.glob("avatar.*"):
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    try:
        folder.rmdir()
    except OSError:
        pass
