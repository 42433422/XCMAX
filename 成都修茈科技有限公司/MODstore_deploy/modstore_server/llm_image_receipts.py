"""Bounded image receipts in the existing account-owned studio asset store."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, update

from modstore_server.infrastructure.private_asset_storage import require_private_directory
from modstore_server.models import User, UserStudioAsset, get_session_factory

_MIME = "application/vnd.xcmax.image-receipt+json"
_MAX_BYTES = 24 * 1024 * 1024 + 4096
_ACCOUNT_BYTES = 256 * 1024 * 1024
_ACCOUNT_OBJECTS = 1024


def _root() -> Path:
    from modstore_server.workbench_studio_assets_api import _data_root

    try:
        return require_private_directory(_data_root())
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "生图回执需要可用的私有素材目录") from exc


def reserve_image_receipt(user_id: int) -> tuple[int, str]:
    """A database write lock serializes admission across workers, including SQLite."""
    _root()
    with get_session_factory()() as session:
        if (
            session.query(User)
            .filter(User.id == user_id)
            .update({User.id: User.id}, synchronize_session=False)
            != 1
        ):
            raise HTTPException(403, "生图账号不存在")
        used, count = (
            session.query(func.coalesce(func.sum(UserStudioAsset.size_bytes), 0), func.count())
            .filter(UserStudioAsset.user_id == user_id, UserStudioAsset.mime_type == _MIME)
            .one()
        )
        if used + _MAX_BYTES > _ACCOUNT_BYTES or count >= _ACCOUNT_OBJECTS:
            raise HTTPException(429, "生图回执空间不足，请先在素材库清理已保存的图片")
        filename = f"generated-{uuid.uuid4().hex}.json"
        row = UserStudioAsset(
            user_id=user_id,
            kind="image",
            filename=filename,
            mime_type=_MIME,
            size_bytes=_MAX_BYTES,
        )
        session.add(row)
        session.flush()
        asset_id = int(row.id)
        session.commit()
        return asset_id, filename


def save_image_receipt(user_id: int, asset: tuple[int, str], images: list[str]) -> str:
    if not images or len(images) > 4 or not all(isinstance(image, str) for image in images):
        raise HTTPException(502, "生图回执格式无效")
    data = json.dumps(images, ensure_ascii=False).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise HTTPException(502, "生图回执超过允许大小")
    root = _root()
    asset_id, filename = asset
    relpath = f"user_studio_assets/{user_id}/{asset_id}/{filename}"
    path = root / relpath
    if path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
        raise HTTPException(503, "生图回执存储路径无效")
    with get_session_factory()() as session:
        row = (
            session.query(UserStudioAsset)
            .filter_by(id=asset_id, user_id=user_id, mime_type=_MIME, filename=filename)
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.storage_relpath:
            raise HTTPException(409, "生图回执空间预留已失效")
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        created = saved = False
        try:
            with path.open("xb") as target:
                created = True
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            path.chmod(0o600)
            session.execute(
                update(UserStudioAsset)
                .where(UserStudioAsset.id == asset_id)
                .values(storage_relpath=relpath, size_bytes=len(data))
            )
            session.commit()
            saved = True
            return hashlib.sha256(data).hexdigest()
        finally:
            if created and not saved:
                path.unlink(missing_ok=True)


def discard_image_receipt(user_id: int, asset: tuple[int, str]) -> None:
    """Only release an unwritten reservation; saved results remain recoverable."""
    with get_session_factory()() as session:
        session.query(UserStudioAsset).filter_by(
            id=asset[0], user_id=user_id, mime_type=_MIME, filename=asset[1], storage_relpath=""
        ).delete(synchronize_session=False)
        session.commit()


def materialize_image_receipt(user_id: int, receipt: dict) -> dict:
    """Keep the public response compatible while the journal stores only an asset id."""
    if "image_asset" not in receipt:
        return receipt
    asset = receipt["image_asset"]
    if (
        not isinstance(asset, dict)
        or type(asset.get("id")) is not int
        or asset["id"] < 1
        or not isinstance(asset.get("filename"), str)
        or not re.fullmatch(r"generated-[a-f0-9]{32}\.json", asset["filename"])
        or not isinstance(asset.get("sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"])
    ):
        raise HTTPException(409, "生图回执引用无效")
    with get_session_factory()() as session:
        row = (
            session.query(UserStudioAsset)
            .filter_by(id=asset["id"], user_id=user_id, mime_type=_MIME, filename=asset["filename"])
            .one_or_none()
        )
        if row is None or not row.storage_relpath:
            raise HTTPException(410, "已保存的生图回执已删除")
        relpath = str(row.storage_relpath)
    from modstore_server.workbench_studio_assets_api import _resolved_file_path

    path = _resolved_file_path(_root(), relpath)
    try:
        with path.open("rb") as source:
            data = source.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("invalid receipt bytes")
        images = json.loads(data)
        if not isinstance(images, list) or not 1 <= len(images) <= 4:
            raise ValueError("invalid receipt")
        if not all(isinstance(image, str) for image in images):
            raise ValueError("invalid image")
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "已保存的生图回执暂不可读") from exc
    return {**receipt, "images": images}
