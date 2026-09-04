# mypy: disable-error-code="arg-type"
"""XCAGI 桌面更新的真实安装回执。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.db.delivery_commerce import UpdateInstallationReceipt
from modstore_server.models import User

router = APIRouter(prefix="/api/update-installations", tags=["update-installations"])


class UpdateInstallationReceiptBody(BaseModel):
    installation_id: str = Field(..., min_length=16, max_length=64)
    idempotency_key: str = Field(..., min_length=16, max_length=192)
    channel: str = Field(default="stable", pattern="^(stable|staging)$")
    platform: str = Field(default="", max_length=32)
    target_version: str = Field(default="", max_length=64)
    target_build_sha: str = Field(default="", pattern="^$|^[0-9a-fA-F]{40}$")
    installed_version: str = Field(default="", max_length=64)
    installed_build_sha: str = Field(default="", pattern="^$|^[0-9a-fA-F]{40}$")
    status: Literal["installed", "failed", "rolled_back", "revoked"]
    error: str = Field(default="", max_length=4000)
    source: str = Field(default="desktop_ota", max_length=32)
    reported_at: datetime | None = None


def _serialize(row: UpdateInstallationReceipt) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "installation_id": row.installation_id,
        "channel": row.channel,
        "platform": row.platform,
        "target_version": row.target_version,
        "target_build_sha": row.target_build_sha,
        "installed_version": row.installed_version,
        "installed_build_sha": row.installed_build_sha,
        "status": row.status,
        "error": row.error,
        "source": row.source,
        "reported_at": row.reported_at.isoformat() if row.reported_at else "",
    }


@router.post("/receipts")
def record_update_installation_receipt(
    body: UpdateInstallationReceiptBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.status == "installed" and not body.installed_build_sha:
        raise HTTPException(422, "成功安装回执必须包含完整 installed_build_sha")
    if (
        body.status == "installed"
        and body.target_build_sha
        and body.target_build_sha.lower() != body.installed_build_sha.lower()
    ):
        raise HTTPException(422, "成功安装回执的目标 SHA 与实际 SHA 不一致")
    existing = (
        db.query(UpdateInstallationReceipt)
        .filter(UpdateInstallationReceipt.idempotency_key == body.idempotency_key)
        .first()
    )
    if existing:
        if int(existing.user_id) != int(user.id):
            raise HTTPException(409, "安装回执幂等键已被其他账号使用")
        return {"ok": True, "duplicate": True, "receipt": _serialize(existing)}
    received_at = datetime.now(UTC)
    if body.reported_at is not None:
        client_time = body.reported_at
        if client_time.tzinfo is None:
            raise HTTPException(422, "客户端回执时间必须包含时区")
        if abs(received_at - client_time.astimezone(UTC)) > timedelta(minutes=15):
            raise HTTPException(422, "客户端回执时间与服务端相差超过 15 分钟")
    reported_at = received_at.replace(tzinfo=None)
    row = UpdateInstallationReceipt(
        user_id=int(user.id),
        installation_id=body.installation_id.strip(),
        idempotency_key=body.idempotency_key.strip(),
        channel=body.channel,
        platform=body.platform.strip(),
        target_version=body.target_version.strip(),
        target_build_sha=body.target_build_sha.strip().lower(),
        installed_version=body.installed_version.strip(),
        installed_build_sha=body.installed_build_sha.strip().lower(),
        status=body.status,
        error=body.error.strip(),
        source=body.source.strip() or "desktop_ota",
        reported_at=reported_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "duplicate": False, "receipt": _serialize(row)}


@router.get("/receipts")
def list_update_installation_receipts(
    target_build_sha: str = Query(default="", max_length=128),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    query = db.query(UpdateInstallationReceipt)
    if target_build_sha.strip():
        query = query.filter(UpdateInstallationReceipt.target_build_sha == target_build_sha.strip())
    rows = (
        query.order_by(
            UpdateInstallationReceipt.reported_at.desc(),
            UpdateInstallationReceipt.id.desc(),
        )
        .limit(limit)
        .all()
    )
    latest_by_installation: dict[str, UpdateInstallationReceipt] = {}
    for row in rows:
        latest_by_installation.setdefault(str(row.installation_id), row)
    latest = list(latest_by_installation.values())
    summary = {
        "reported_devices": len(latest),
        "installed_devices": sum(1 for row in latest if row.status == "installed"),
        "failed_devices": sum(1 for row in latest if row.status in {"failed", "rolled_back"}),
        "rolled_back_devices": sum(1 for row in latest if row.status == "rolled_back"),
    }
    return {"items": [_serialize(row) for row in rows], "summary": summary}
