"""Paid asset -> authenticated XCAGI desktop installation command channel."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.asset_installation_presenter import serialize_install_command
from modstore_server.api.deps import get_current_user, get_db
from modstore_server.db.catalog import CatalogItem, Purchase
from modstore_server.db.billing import Entitlement
from modstore_server.db.delivery_commerce import AssetInstallCommand, UpdateInstallationReceipt
from modstore_server.models import User

router = APIRouter(prefix="/api/asset-installations", tags=["asset-installations"])

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTALLABLE_ARTIFACTS = frozenset({"mod", "employee_pack", "bundle"})


class QueueAssetInstallBody(BaseModel):
    catalog_id: int = Field(..., ge=1)
    installation_id: str = Field(default="", max_length=64)
    idempotency_key: str = Field(default="", max_length=192)


class ClaimAssetInstallBody(BaseModel):
    installation_id: str = Field(..., min_length=16, max_length=64)


class CompleteAssetInstallBody(BaseModel):
    installation_id: str = Field(..., min_length=16, max_length=64)
    status: Literal["installed", "failed"]
    installed_mod_id: str = Field(default="", max_length=128)
    installed_version: str = Field(default="", max_length=64)
    error: str = Field(default="", max_length=4000)
    result: dict = Field(default_factory=dict)


def _latest_owned_installation_ids(session: Session, user_id: int) -> set[str]:
    rows = (
        session.query(UpdateInstallationReceipt)
        .filter(UpdateInstallationReceipt.user_id == int(user_id))
        .order_by(UpdateInstallationReceipt.reported_at.desc(), UpdateInstallationReceipt.id.desc())
        .limit(500)
        .all()
    )
    return {
        str(row.installation_id or "").strip()
        for row in rows
        if str(row.installation_id or "").strip()
    }


def _purchase_is_current(session: Session, user_id: int, catalog_id: int) -> bool:
    """An inactive entitlement proves a gateway purchase was refunded/revoked.

    Legacy wallet purchases predate entitlements and remain valid when no entitlement row exists.
    """
    rows = (
        session.query(Entitlement)
        .filter(Entitlement.user_id == int(user_id), Entitlement.catalog_id == int(catalog_id))
        .all()
    )
    return not rows or any(bool(row.is_active) for row in rows)


def _has_verifiable_artifact(item: CatalogItem) -> bool:
    return bool(_SHA256_RE.fullmatch(str(item.sha256 or "").strip().lower()))


def _is_desktop_installable(item: CatalogItem) -> bool:
    return str(item.artifact or "mod").strip().lower() in _INSTALLABLE_ARTIFACTS


def queue_install_command(
    session: Session,
    *,
    user_id: int,
    purchase: Purchase,
    catalog_id: int,
    installation_id: str = "*",
    source: str,
    source_event_id: str = "",
    idempotency_key: str = "",
) -> tuple[AssetInstallCommand, bool]:
    if int(purchase.user_id) != int(user_id) or int(purchase.catalog_id) != int(catalog_id):
        raise ValueError("安装命令与购买记录归属不一致")
    target = str(installation_id or "*").strip() or "*"
    # Never put a caller-controlled idempotency key in the global unique column.
    # Scope and hash it so another account cannot collide with or read this row.
    request_key = str(idempotency_key or source_event_id or "").strip()
    material = (
        f"asset-install:{int(user_id)}:{int(purchase.id)}:{target}:" f"{source}:{request_key}"
    )
    stable_key = hashlib.sha256(material.encode("utf-8")).hexdigest()
    existing = (
        session.query(AssetInstallCommand)
        .filter(AssetInstallCommand.idempotency_key == stable_key)
        .first()
    )
    if existing is not None:
        return existing, False
    row = AssetInstallCommand(
        user_id=int(user_id),
        purchase_id=int(purchase.id),
        catalog_id=int(catalog_id),
        installation_id=target,
        idempotency_key=stable_key,
        source=str(source or "user_click")[:32],
        source_event_id=str(source_event_id or "")[:192],
        status="pending",
    )
    session.add(row)
    session.flush()
    return row, True


def queue_paid_asset_installation(*, user_id: int, catalog_id: int, event_id: str) -> dict:
    """Called by ``payment.paid`` after entitlement fulfilment.

    This is the server-side active push decision.  The transport is a durable
    command queue because customer desktops are normally behind NAT and may be
    offline at callback time.
    """

    if int(user_id or 0) <= 0 or int(catalog_id or 0) <= 0:
        return {"queued": 0, "reason": "not_an_item_payment"}
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    with sf() as session:
        purchase = (
            session.query(Purchase)
            .filter(Purchase.user_id == int(user_id), Purchase.catalog_id == int(catalog_id))
            .order_by(Purchase.id.desc())
            .first()
        )
        item = session.query(CatalogItem).filter(CatalogItem.id == int(catalog_id)).first()
        if purchase is None or item is None:
            return {"queued": 0, "reason": "purchase_not_fulfilled_yet"}
        if not _purchase_is_current(session, int(user_id), int(catalog_id)):
            return {"queued": 0, "reason": "entitlement_revoked"}
        if not _is_desktop_installable(item):
            return {"queued": 0, "reason": "artifact_not_desktop_installable"}
        if not _has_verifiable_artifact(item):
            return {"queued": 0, "reason": "artifact_sha256_missing"}
        row, created = queue_install_command(
            session,
            user_id=int(user_id),
            purchase=purchase,
            catalog_id=int(catalog_id),
            installation_id="*",
            source="payment_callback",
            source_event_id=event_id,
        )
        session.commit()
        return {"queued": 1 if created else 0, "command_id": int(row.id), "duplicate": not created}


def revoke_asset_install_commands_for_order(*, user_id: int, order_no: str) -> int:
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    with sf() as session:
        catalog_ids = {
            int(row.catalog_id)
            for row in session.query(Entitlement)
            .filter(
                Entitlement.user_id == int(user_id),
                Entitlement.source_order_id == str(order_no or "").strip(),
                Entitlement.catalog_id.isnot(None),
            )
            .all()
            if row.catalog_id is not None
        }
        source_event_id = f"payment.paid:{str(order_no or '').strip()}"
        rows = (
            session.query(AssetInstallCommand)
            .filter(
                AssetInstallCommand.user_id == int(user_id),
                AssetInstallCommand.status.in_(["pending", "failed", "claimed"]),
            )
            .all()
        )
        changed = 0
        for row in rows:
            exact_order_command = str(row.source_event_id or "") == source_event_id
            no_remaining_catalog_right = int(
                row.catalog_id
            ) in catalog_ids and not _purchase_is_current(
                session, int(user_id), int(row.catalog_id)
            )
            if not exact_order_command and not no_remaining_catalog_right:
                continue
            row.status = "revoked"
            row.error = "payment_refunded"
            session.add(row)
            changed += 1
        session.commit()
        return changed


@router.post("/commands")
def create_asset_install_command(
    body: QueueAssetInstallBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    purchase = (
        db.query(Purchase)
        .filter(Purchase.user_id == int(user.id), Purchase.catalog_id == int(body.catalog_id))
        .order_by(Purchase.id.desc())
        .first()
    )
    item = db.query(CatalogItem).filter(CatalogItem.id == int(body.catalog_id)).first()
    if purchase is None or item is None:
        raise HTTPException(403, "该账号没有此资产的有效购买记录")
    if not _purchase_is_current(db, int(user.id), int(body.catalog_id)):
        raise HTTPException(403, "该资产购买权益已退款或撤销")
    if not _is_desktop_installable(item):
        raise HTTPException(409, "该资产类型仅支持下载，不能作为 XCMAX 扩展安装")
    if not _has_verifiable_artifact(item):
        raise HTTPException(409, "资产缺少可验证的 SHA256，已阻止安装")
    target = body.installation_id.strip() or "*"
    if target != "*" and target not in _latest_owned_installation_ids(db, int(user.id)):
        raise HTTPException(403, "目标设备不属于当前账号")
    row, created = queue_install_command(
        db,
        user_id=int(user.id),
        purchase=purchase,
        catalog_id=int(item.id),
        installation_id=target,
        source="user_click",
        idempotency_key=body.idempotency_key,
    )
    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "queued": created,
        "duplicate": not created,
        "command": serialize_install_command(row, item),
    }


@router.get("/commands")
def list_asset_install_commands(
    installation_id: str = Query(default="", max_length=64),
    pending_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(AssetInstallCommand).filter(AssetInstallCommand.user_id == int(user.id))
    target = installation_id.strip()
    if target:
        if target not in _latest_owned_installation_ids(db, int(user.id)):
            raise HTTPException(403, "目标设备不属于当前账号")
        query = query.filter(AssetInstallCommand.installation_id.in_(["*", target]))
    if pending_only:
        # A desktop may restart after claiming but before reporting the result.
        # Returning its device-bound claim makes the delivery resumable.
        query = query.filter(AssetInstallCommand.status.in_(["pending", "failed", "claimed"]))
    rows = query.order_by(AssetInstallCommand.id.asc()).limit(limit).all()
    item_ids = {int(row.catalog_id) for row in rows}
    items = (
        {
            int(item.id): item
            for item in db.query(CatalogItem).filter(CatalogItem.id.in_(item_ids)).all()
        }
        if item_ids
        else {}
    )
    return {
        "items": [serialize_install_command(row, items.get(int(row.catalog_id))) for row in rows],
        "total": len(rows),
    }


@router.get("/commands/{command_id}")
def get_asset_install_command(
    command_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(AssetInstallCommand)
        .filter(
            AssetInstallCommand.id == int(command_id), AssetInstallCommand.user_id == int(user.id)
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "安装命令不存在")
    item = db.query(CatalogItem).filter(CatalogItem.id == int(row.catalog_id)).first()
    return {"ok": True, "command": serialize_install_command(row, item)}


@router.post("/commands/{command_id}/claim")
def claim_asset_install_command(
    command_id: int,
    body: ClaimAssetInstallBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    installation_id = body.installation_id.strip()
    if installation_id not in _latest_owned_installation_ids(db, int(user.id)):
        raise HTTPException(403, "目标设备不属于当前账号")
    row = (
        db.query(AssetInstallCommand)
        .filter(
            AssetInstallCommand.id == int(command_id), AssetInstallCommand.user_id == int(user.id)
        )
        .with_for_update()
        .first()
    )
    if row is None:
        raise HTTPException(404, "安装命令不存在")
    if not _purchase_is_current(db, int(user.id), int(row.catalog_id)):
        row.status = "revoked"
        row.error = "payment_refunded"
        db.add(row)
        db.commit()
        raise HTTPException(403, "该资产购买权益已退款或撤销")
    item = db.query(CatalogItem).filter(CatalogItem.id == int(row.catalog_id)).first()
    if item is None:
        raise HTTPException(410, "资产已从目录移除")
    if not _is_desktop_installable(item):
        raise HTTPException(409, "该资产类型不能作为 XCMAX 扩展安装")
    if not _has_verifiable_artifact(item):
        raise HTTPException(409, "资产缺少可验证的 SHA256，已阻止安装")
    if row.installation_id not in {"*", installation_id}:
        raise HTTPException(409, "安装命令已由其他设备领取")
    if row.status == "installed":
        return {"ok": True, "duplicate": True, "command": serialize_install_command(row, item)}
    if row.status not in {"pending", "failed", "claimed"}:
        raise HTTPException(409, f"安装命令当前状态不可领取：{row.status}")
    row.installation_id = installation_id
    row.status = "claimed"
    row.attempt_count = int(row.attempt_count or 0) + 1
    row.error = ""
    row.claimed_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "duplicate": False, "command": serialize_install_command(row, item)}


@router.get("/commands/{command_id}/download")
def download_claimed_asset_install_command(
    command_id: int,
    installation_id: str = Query(..., min_length=16, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream an asset only while the purchase and device-bound command remain valid."""
    target = installation_id.strip()
    if target not in _latest_owned_installation_ids(db, int(user.id)):
        raise HTTPException(403, "目标设备不属于当前账号")
    row = (
        db.query(AssetInstallCommand)
        .filter(
            AssetInstallCommand.id == int(command_id), AssetInstallCommand.user_id == int(user.id)
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "安装命令不存在")
    if row.status != "claimed" or str(row.installation_id or "") != target:
        raise HTTPException(409, "安装命令尚未由当前设备领取")
    if not _purchase_is_current(db, int(user.id), int(row.catalog_id)):
        row.status = "revoked"
        row.error = "payment_refunded"
        db.add(row)
        db.commit()
        raise HTTPException(403, "该资产购买权益已退款或撤销")
    item = db.query(CatalogItem).filter(CatalogItem.id == int(row.catalog_id)).first()
    if item is None or not str(item.stored_filename or "").strip():
        raise HTTPException(410, "资产安装包已移除")
    if not _is_desktop_installable(item):
        raise HTTPException(409, "该资产类型不能作为 XCMAX 扩展安装")
    if not _has_verifiable_artifact(item):
        raise HTTPException(409, "资产缺少可验证的 SHA256，已阻止下载")
    from modstore_server.catalog_store import files_dir

    name = str(item.stored_filename).strip()
    if Path(name).name != name:
        raise HTTPException(410, "资产安装包路径无效")
    path = (files_dir() / name).resolve()
    root = files_dir().resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(410, "资产安装包文件缺失")

    def generate():
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="asset-{int(item.id)}.zip"',
            "Content-Length": str(path.stat().st_size),
            "X-Content-SHA256": str(item.sha256).strip().lower(),
        },
    )


@router.post("/commands/{command_id}/result")
def complete_asset_install_command(
    command_id: int,
    body: CompleteAssetInstallBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(AssetInstallCommand)
        .filter(
            AssetInstallCommand.id == int(command_id), AssetInstallCommand.user_id == int(user.id)
        )
        .with_for_update()
        .first()
    )
    if row is None:
        raise HTTPException(404, "安装命令不存在")
    if str(row.installation_id) != body.installation_id.strip():
        raise HTTPException(409, "安装结果设备与领取设备不一致")
    if row.status == "installed":
        return {"ok": True, "duplicate": True, "command": serialize_install_command(row)}
    if row.status != "claimed":
        raise HTTPException(409, "安装命令尚未由当前设备领取")
    if not _purchase_is_current(db, int(user.id), int(row.catalog_id)):
        row.status = "revoked"
        row.error = "payment_refunded"
        db.add(row)
        db.commit()
        raise HTTPException(403, "该资产购买权益已退款或撤销")
    if body.status == "installed":
        item = db.query(CatalogItem).filter(CatalogItem.id == int(row.catalog_id)).first()
        if item is None:
            raise HTTPException(410, "资产已从目录移除")
        if body.installed_mod_id.strip() != str(item.pkg_id or "").strip():
            raise HTTPException(409, "安装回执的资产 ID 与命令不一致")
        if body.installed_version.strip() != str(item.version or "").strip():
            raise HTTPException(409, "安装回执的资产版本与命令不一致")
    row.status = body.status
    row.error = body.error.strip() if body.status == "failed" else ""
    row.result_json = json.dumps(
        {
            "installed_mod_id": body.installed_mod_id.strip(),
            "installed_version": body.installed_version.strip(),
            "result": body.result,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    row.completed_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "duplicate": False, "command": serialize_install_command(row)}


__all__ = [
    "router",
    "queue_install_command",
    "queue_paid_asset_installation",
    "revoke_asset_install_commands_for_order",
]
