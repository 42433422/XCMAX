"""本机文件只读授权服务：授权、撤销、FDA 探测与读取边界。"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, cast

from app.application.local_file_access.paths import (
    LocalFilePathError,
    create_grant_root,
    resolve_authorized_path,
)
from app.db.models.local_file import LocalFileDocument, LocalFileGrant
from app.db.session import get_db
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.logging.audit_logger import audit_log
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

DATASET_ID = "local-files"
_TCC_PROBE = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
_SAFARI_PROBE = Path.home() / "Library/Safari/Bookmarks.plist"


class LocalFileAccessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_full_disk_access() -> str:
    """返回 granted / denied / unknown / not_required。

    应用不能代替用户开启 macOS「完全磁盘访问权限」，只能读取受保护路径判断。
    """
    if sys.platform != "darwin":
        return "not_required"
    for probe in (_TCC_PROBE, _SAFARI_PROBE):
        try:
            with probe.open("rb") as handle:
                handle.read(1)
            return "granted"
        except FileNotFoundError:
            continue
        except PermissionError:
            return "denied"
        except OSError:
            continue
    return "unknown"


def _serialize(grant: LocalFileGrant) -> dict[str, Any]:
    return {
        "id": grant.id,
        "mode": grant.mode,
        "root_path": grant.root_path,
        "display_name": grant.display_name,
        "is_active": bool(grant.is_active),
        "device_id": grant.device_id,
        "last_scan_at": grant.last_scan_at.isoformat() if grant.last_scan_at else None,
        "scan_status": grant.scan_status,
        "scan_error": grant.scan_error,
        "indexed_count": grant.indexed_count,
        "skipped_count": grant.skipped_count,
        "error_count": grant.error_count,
    }


def list_grants(*, owner_id: int, tenant: int) -> list[dict[str, Any]]:
    with tenant_scope(tenant), get_db() as db:
        rows = (
            db.query(LocalFileGrant)
            .filter(LocalFileGrant.owner_user_id == int(owner_id))
            .order_by(LocalFileGrant.id.desc())
            .all()
        )
        return [_serialize(row) for row in rows]


def get_grant(*, owner_id: int, tenant: int, grant_id: int) -> LocalFileGrant:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileGrant)
            .filter(
                LocalFileGrant.id == int(grant_id),
                LocalFileGrant.owner_user_id == int(owner_id),
            )
            .first()
        )
        if row is None:
            raise LocalFileAccessError("local_file_grant_not_found", "授权不存在或不属于当前账号")
        db.expunge(row)
        return cast(LocalFileGrant, row)


def create_grant(
    *,
    owner_id: int,
    tenant: int,
    mode: str,
    root_path: str,
    device_id: str = "",
) -> dict[str, Any]:
    normalized_mode = str(mode or "folder").strip()
    if normalized_mode not in {"folder", "full_disk"}:
        raise LocalFileAccessError("local_file_mode_invalid", "授权模式只能是 folder 或 full_disk")
    if normalized_mode == "full_disk" and detect_full_disk_access() == "denied":
        raise LocalFileAccessError(
            "local_file_full_disk_denied",
            "需要在系统设置中给应用开启「完全磁盘访问权限」后才能使用整机模式",
        )
    try:
        root = create_grant_root(normalized_mode, root_path or "~")
    except LocalFilePathError as exc:
        raise LocalFileAccessError("local_file_root_invalid", str(exc)) from exc
    with tenant_scope(tenant), get_db() as db:
        existing = (
            db.query(LocalFileGrant)
            .filter(
                LocalFileGrant.owner_user_id == int(owner_id),
                LocalFileGrant.root_path == str(root),
            )
            .first()
        )
        if existing is not None:
            existing.is_active = True
            existing.mode = normalized_mode
            existing.display_name = existing.display_name or root.name or str(root)
            db.commit()
            db.refresh(existing)
            result = _serialize(existing)
        else:
            grant = LocalFileGrant(
                owner_user_id=int(owner_id),
                device_id=str(device_id or "")[:128],
                mode=normalized_mode,
                root_path=str(root),
                display_name=root.name or str(root),
                is_active=True,
                authorized_via="desktop",
            )
            db.add(grant)
            db.commit()
            db.refresh(grant)
            result = _serialize(grant)
    audit_log(
        "local_file_access.grant",
        actor_id=owner_id,
        details={"grant_id": result["id"], "mode": normalized_mode, "root_path": str(root)},
    )
    return result


def revoke_grant(*, owner_id: int, tenant: int, grant_id: int) -> dict[str, Any]:
    """先停用授权（立即阻断读取），再交给索引任务清理已入库内容。"""
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileGrant)
            .filter(
                LocalFileGrant.id == int(grant_id),
                LocalFileGrant.owner_user_id == int(owner_id),
            )
            .first()
        )
        if row is None:
            raise LocalFileAccessError("local_file_grant_not_found", "授权不存在或不属于当前账号")
        row.is_active = False
        row.scan_status = "revoked"
        row.updated_at = utc_now_naive()
        db.commit()
    try:
        from app.application.local_file_access.indexer import request_purge

        request_purge(int(grant_id), int(owner_id), int(tenant))
    except RECOVERABLE_ERRORS:
        logger.warning("local file purge scheduling failed", exc_info=True)
    audit_log(
        "local_file_access.revoke",
        actor_id=owner_id,
        details={"grant_id": int(grant_id)},
    )
    return {"id": int(grant_id), "is_active": False, "scan_status": "revoked"}


def grant_for_read(*, owner_id: int, tenant: int, grant_id: int) -> LocalFileGrant:
    grant = get_grant(owner_id=owner_id, tenant=tenant, grant_id=grant_id)
    if not grant.is_active:
        raise LocalFileAccessError("local_file_grant_inactive", "授权已撤销，无法读取该目录")
    return grant


def assert_readable(grant: LocalFileGrant, candidate: str | os.PathLike[str]) -> Path:
    try:
        path = resolve_authorized_path(grant, candidate)
    except LocalFilePathError as exc:
        raise LocalFileAccessError("local_file_denied", str(exc)) from exc
    audit_log(
        "local_file_access.read",
        actor_id=grant.owner_user_id,
        details={"grant_id": grant.id, "path": str(path)},
    )
    return path


def pending_documents(*, owner_id: int, tenant: int, grant_id: int) -> int:
    with tenant_scope(tenant), get_db() as db:
        return cast(
            int,
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.status != "deleted",
            )
            .count(),
        )
