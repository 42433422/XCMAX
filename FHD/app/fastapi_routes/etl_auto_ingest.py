"""ETL auto-ingest + progress API (split from etl.py to keep router ≤20 routes)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.db.session import get_db_dependency
from app.infrastructure.auth.dependencies import require_permission
from app.mod_sdk.product_skus import resolve_product_sku


def _feature_gate() -> None:
    flag = str(os.environ.get("FHD_ETL_CENTER_ENABLED") or "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "ETL_CENTER_DISABLED", "message": "数据对接中心尚未启用"},
        )
    if resolve_product_sku() != "enterprise":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ETL_ENTERPRISE_REQUIRED",
                "message": "数据对接中心仅在企业版中提供",
            },
        )


def _error_boundary() -> Iterator[None]:
    try:
        yield
    except EtlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


router = APIRouter(
    prefix="/api/etl",
    tags=["etl-auto-ingest"],
    dependencies=[Depends(_feature_gate), Depends(_error_boundary)],
)

_read = require_permission("etl.read")
_execute = require_permission("etl.execute")
_rollback = require_permission("etl.rollback")


def _user_id(user: Any) -> int:
    value = getattr(user, "id", None)
    if value is None:
        value = getattr(user, "user_id", None)
    if value is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "ETL_USER_REQUIRED", "message": "请先登录"},
        )
    return int(value)


@router.post("/auto-ingest")
def auto_ingest(
    body: dict[str, Any],
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    """After intake/template save: write knowledge + matching business domain, record batch for 撤回."""
    from app.application.etl.auto_ingest_service import get_auto_ingest_service
    from app.infrastructure.tenant_scope import tenant_id_for_write

    source_path = str(body.get("source_path") or "").strip()
    if not source_path:
        raise HTTPException(
            status_code=400,
            detail={"code": "ETL_AUTO_INGEST_PATH_REQUIRED", "message": "source_path 必填"},
        )
    labels = body.get("labels") if isinstance(body.get("labels"), list) else []
    async_mode = bool(body.get("async"))
    service = get_auto_ingest_service()
    kwargs = {
        "owner_user_id": _user_id(user),
        "tenant_id": int(tenant_id_for_write()),
        "source_path": source_path,
        "file_name": str(body.get("file_name") or ""),
        "template_id": str(body.get("template_id") or ""),
        "review_id": str(body.get("review_id") or ""),
        "classification_id": str(body.get("classification_id") or ""),
        "composer_note": str(body.get("composer_note") or ""),
        "labels": [str(x) for x in labels],
    }
    if async_mode:
        batch = service.start_background(**kwargs)
    else:
        batch = service.run(db, **kwargs)
    return {"success": True, "data": batch}


@router.get("/auto-ingest/batches")
def list_auto_ingest_batches(
    limit: int = Query(default=50, ge=1, le=200),
    mine: bool = Query(default=True),
    user: Any = Depends(_read),
):
    from app.application.etl.auto_ingest_service import get_auto_ingest_service
    from app.infrastructure.tenant_scope import tenant_id_for_write

    owner = _user_id(user) if mine else None
    items = get_auto_ingest_service().list_batches(
        tenant_id=int(tenant_id_for_write()),
        owner_user_id=owner,
        limit=limit,
    )
    return {"success": True, "data": items}


@router.get("/auto-ingest/batches/{batch_id}")
def get_auto_ingest_batch(batch_id: str, user: Any = Depends(_read)):
    from app.application.etl.auto_ingest_service import get_auto_ingest_service
    from app.infrastructure.tenant_scope import tenant_id_for_write

    batch = get_auto_ingest_service().get_batch(
        tenant_id=int(tenant_id_for_write()), batch_id=batch_id
    )
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ETL_AUTO_INGEST_NOT_FOUND", "message": "入库批次不存在"},
        )
    if int(batch.get("owner_user_id") or 0) != _user_id(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "ETL_AUTO_INGEST_FORBIDDEN", "message": "无权查看该批次"},
        )
    return {"success": True, "data": batch}


@router.get("/auto-ingest/batches/{batch_id}/progress")
def get_auto_ingest_progress(batch_id: str, user: Any = Depends(_read)):
    """Real KB/business progress for UI bars — reads ledger stages, never invents timers."""
    from app.application.etl.auto_ingest_service import get_auto_ingest_service
    from app.infrastructure.tenant_scope import tenant_id_for_write

    progress = get_auto_ingest_service().get_progress(
        tenant_id=int(tenant_id_for_write()),
        owner_user_id=_user_id(user),
        batch_id=batch_id,
    )
    return {"success": True, "data": progress}


@router.post("/auto-ingest/batches/{batch_id}/withdraw")
def withdraw_auto_ingest_batch(
    batch_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_rollback),
):
    """审批中心撤回：回滚知识库 + 业务库本次批次写入。"""
    from app.application.etl.auto_ingest_service import get_auto_ingest_service
    from app.infrastructure.tenant_scope import tenant_id_for_write

    batch = get_auto_ingest_service().withdraw(
        db,
        tenant_id=int(tenant_id_for_write()),
        owner_user_id=_user_id(user),
        batch_id=batch_id,
    )
    return {"success": True, "data": batch}
