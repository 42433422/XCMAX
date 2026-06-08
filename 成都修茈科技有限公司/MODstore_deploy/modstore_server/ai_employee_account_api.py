"""AI 员工账号池——管理员 CRUD + 内部查询 API。

## 路由概览

- ``GET    /api/admin/ai-accounts``           列表（支持 platform/employee_id/status 过滤）
- ``POST   /api/admin/ai-accounts``           新建账号 + 落地密钥
- ``GET    /api/admin/ai-accounts/{id}``      单个账号详情（不返回明文密钥）
- ``PATCH  /api/admin/ai-accounts/{id}``      改派 employee_id / 改状态 / 改备注
- ``POST   /api/admin/ai-accounts/{id}/rotate`` 轮换密钥（覆盖密钥文件）
- ``DELETE /api/admin/ai-accounts/{id}``      删除账号 + 销毁密钥文件

返回 DTO 字段都不含明文密钥，仅返回 ``has_secret`` 布尔标。

## 内部查询

``lookup_active_account_for`` 给 ``butler_qq_bridge`` 之类的 runtime 使用：
按 ``employee_id + platform`` 找当前 active 的账号，并把密钥文件解开成
dict 返回；查不到返回 ``None``，让上层走 ENV fallback。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from modstore_server.ai_employee_account_secrets import (
    delete_secret,
    read_secret,
    secret_path_for,
    validate_qq_secret,
    write_secret,
)
from modstore_server.api.deps import require_admin
from modstore_server.models import User, get_session_factory
from modstore_server.models_ai_accounts import AIEmployeeAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/ai-accounts", tags=["admin-ai-accounts"])


# ─── DTO ─────────────────────────────────────────────────────────────


class CreateAccountDTO(BaseModel):
    platform: str = Field(..., description="qq / wechat / email / ...")
    external_id: str = Field(..., description="该平台上的对外 id，如 QQ 号")
    employee_id: str = Field(..., description="挂到哪位 AI 员工名下，如 xc-digital-butler")
    display_name: str = ""
    sandbox: bool = False
    notes: str = ""
    secret: Dict[str, Any] = Field(..., description="平台凭证（明文，仅在创建时一次性传入）")


class UpdateAccountDTO(BaseModel):
    employee_id: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None
    sandbox: Optional[bool] = None
    notes: Optional[str] = None


class RotateSecretDTO(BaseModel):
    secret: Dict[str, Any]


# ─── 视图序列化 ──────────────────────────────────────────────────────


def _channel_paths(platform: str, employee_id: str) -> Dict[str, Any]:
    """按平台 + 员工拼出该账号的"入站渠道地址"——给前端直接复制贴到 QQ 后台用。

    QQ 平台暴露两条同等的 URL：

    - ``/api/agent/butler/qq/by-employee/{employee_id}/webhook``
      新员工首选，由 ``butler_qq_bridge`` 按 employee_id 解析凭证。
    - ``/api/agent/butler/qq/{webhook_key}/webhook``
      历史 webhook_key（task-router / employee-interview）；其他 platform
      暂不返回，避免误用。

    只是路径字符串，不含 host——前端拼协议域名即可。
    """
    plat = (platform or "").lower()
    if plat != "qq":
        return {"platform": plat, "paths": []}
    eid = (employee_id or "").strip()
    paths: List[Dict[str, str]] = []
    if eid:
        paths.append(
            {
                "label": "通用 webhook（按 employee_id）",
                "path": f"/api/agent/butler/qq/by-employee/{eid}/webhook",
            }
        )
    try:
        from modstore_server.butler_qq_bridge import _SPECIFIC_WEBHOOKS

        for webhook_key, spec in _SPECIFIC_WEBHOOKS.items():
            if spec.get("employee_id") == eid:
                paths.append(
                    {
                        "label": f"历史 URL（{webhook_key}）",
                        "path": f"/api/agent/butler/qq/{webhook_key}/webhook",
                    }
                )
    except Exception:
        pass
    return {"platform": plat, "paths": paths}


def _to_view(row: AIEmployeeAccount, *, has_secret: Optional[bool] = None) -> Dict[str, Any]:
    """把 ORM 行转成对外字典；不带明文密钥。"""
    if has_secret is None:
        # 没显式传，按 secrets_path 是否落地来判断
        try:
            sp = (row.secrets_path or "").strip()
            has_secret = bool(sp) and (
                read_secret(platform=row.platform, account_id=int(row.id)) is not None
            )
        except Exception:
            has_secret = False
    channel = _channel_paths(row.platform, row.employee_id or "")
    return {
        "id": int(row.id),
        "platform": row.platform,
        "external_id": row.external_id,
        "employee_id": row.employee_id,
        "display_name": row.display_name or "",
        "status": row.status,
        "sandbox": bool(row.sandbox),
        "notes": row.notes or "",
        "secrets_path": row.secrets_path or "",
        "has_secret": bool(has_secret),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "channel": channel,
    }


def _invalidate_runtime_caches() -> None:
    """admin CRUD/轮换后，让 QQ 桥接的凭证、bot ctx 缓存立刻失效。"""
    try:
        from modstore_server.butler_qq_bridge import (
            invalidate_bot_ctx_cache,
            invalidate_creds_cache,
        )

        invalidate_creds_cache()
        invalidate_bot_ctx_cache()
    except Exception:
        logger.debug("invalidate butler_qq_bridge caches failed", exc_info=True)


def _validate_secret_for_platform(platform: str, secret: Dict[str, Any]) -> None:
    """各平台特有 schema 检查；不认得的平台至少要求 secret 非空。"""
    if not isinstance(secret, dict) or not secret:
        raise HTTPException(400, "secret 不能为空")
    if platform == "qq":
        try:
            validate_qq_secret(secret)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


# ─── 内部查询：runtime 用 ──────────────────────────────────────────


def lookup_active_account_for(
    employee_id: str,
    platform: str,
    *,
    sandbox: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """给 runtime 用：按员工 + 平台找当前 active 的账号 + 密钥。

    返回 ``{"id", "external_id", "sandbox", "secret": {...}, "row": orm_row}``，
    若没分配返回 ``None``。``secret`` 取自密钥文件，找不到也会返回 ``None``。
    """
    eid = (employee_id or "").strip()
    plat = (platform or "").strip().lower()
    if not (eid and plat):
        return None

    sf = get_session_factory()
    with sf() as session:
        q = session.query(AIEmployeeAccount).filter(
            AIEmployeeAccount.employee_id == eid,
            AIEmployeeAccount.platform == plat,
            AIEmployeeAccount.status == "active",
        )
        if sandbox is not None:
            q = q.filter(AIEmployeeAccount.sandbox == bool(sandbox))
        row = q.order_by(AIEmployeeAccount.id.desc()).first()
        if not row:
            return None
        secret = read_secret(platform=plat, account_id=int(row.id))
        return {
            "id": int(row.id),
            "external_id": row.external_id,
            "sandbox": bool(row.sandbox),
            "secret": secret,
            "display_name": row.display_name or "",
        }


# ─── 路由实现 ────────────────────────────────────────────────────────


@router.get("")
def list_accounts(
    platform: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        q = session.query(AIEmployeeAccount)
        if platform:
            q = q.filter(AIEmployeeAccount.platform == platform.lower())
        if employee_id:
            q = q.filter(AIEmployeeAccount.employee_id == employee_id)
        if status:
            q = q.filter(AIEmployeeAccount.status == status)

        total = int(q.count() or 0)
        rows = q.order_by(AIEmployeeAccount.id.desc()).offset(offset).limit(limit).all()
        items = [_to_view(r) for r in rows]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("")
def create_account(
    body: CreateAccountDTO,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    plat = body.platform.strip().lower()
    if not plat:
        raise HTTPException(400, "platform 不能为空")
    if not body.external_id.strip():
        raise HTTPException(400, "external_id 不能为空")
    if not body.employee_id.strip():
        raise HTTPException(400, "employee_id 不能为空")
    _validate_secret_for_platform(plat, body.secret)

    sf = get_session_factory()
    with sf() as session:
        row = AIEmployeeAccount(
            platform=plat,
            external_id=body.external_id.strip(),
            employee_id=body.employee_id.strip(),
            display_name=(body.display_name or "").strip(),
            status="active",
            sandbox=bool(body.sandbox),
            notes=(body.notes or "").strip(),
            secrets_path="",
        )
        session.add(row)
        try:
            session.flush()  # 拿到自增 id
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                409, f"账号已存在：platform={plat} external_id={body.external_id}"
            ) from exc

        # 密钥写入：先落文件，再回填 secrets_path 字段。
        try:
            sp = write_secret(
                platform=plat,
                account_id=int(row.id),
                external_id=row.external_id,
                secret=body.secret,
            )
        except Exception as exc:
            session.rollback()
            raise HTTPException(500, f"密钥落地失败：{exc}") from exc

        row.secrets_path = str(sp)
        session.commit()
        session.refresh(row)
        view = _to_view(row, has_secret=True)

    logger.info(
        "ai-account 新建：id=%s platform=%s external=%s employee=%s",
        view["id"],
        view["platform"],
        view["external_id"],
        view["employee_id"],
    )
    _invalidate_runtime_caches()
    return view


@router.get("/{account_id}")
def get_account(
    account_id: int,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        row = session.query(AIEmployeeAccount).filter(AIEmployeeAccount.id == account_id).first()
        if not row:
            raise HTTPException(404, "账号不存在")
        return _to_view(row)


@router.patch("/{account_id}")
def update_account(
    account_id: int,
    body: UpdateAccountDTO,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        row = session.query(AIEmployeeAccount).filter(AIEmployeeAccount.id == account_id).first()
        if not row:
            raise HTTPException(404, "账号不存在")
        if body.employee_id is not None:
            v = body.employee_id.strip()
            if not v:
                raise HTTPException(400, "employee_id 不能改成空")
            row.employee_id = v
        if body.display_name is not None:
            row.display_name = body.display_name.strip()
        if body.status is not None:
            v = body.status.strip()
            if v not in ("active", "disabled", "revoked"):
                raise HTTPException(400, "status 必须是 active/disabled/revoked")
            row.status = v
        if body.sandbox is not None:
            row.sandbox = bool(body.sandbox)
        if body.notes is not None:
            row.notes = body.notes
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(row)
        view = _to_view(row)
    _invalidate_runtime_caches()
    return view


@router.post("/{account_id}/rotate")
def rotate_secret(
    account_id: int,
    body: RotateSecretDTO,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        row = session.query(AIEmployeeAccount).filter(AIEmployeeAccount.id == account_id).first()
        if not row:
            raise HTTPException(404, "账号不存在")
        _validate_secret_for_platform(row.platform, body.secret)
        try:
            sp = write_secret(
                platform=row.platform,
                account_id=int(row.id),
                external_id=row.external_id,
                secret=body.secret,
            )
        except Exception as exc:
            raise HTTPException(500, f"密钥写入失败：{exc}") from exc
        row.secrets_path = str(sp)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(row)
        view = _to_view(row, has_secret=True)
    _invalidate_runtime_caches()
    return view


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        row = session.query(AIEmployeeAccount).filter(AIEmployeeAccount.id == account_id).first()
        if not row:
            raise HTTPException(404, "账号不存在")
        platform = row.platform
        sec_existed = delete_secret(platform=platform, account_id=int(row.id))
        session.delete(row)
        session.commit()
    _invalidate_runtime_caches()
    return {"deleted": True, "secret_file_removed": sec_existed}


# ─── 兼容性：暴露密钥文件路径（仅给运维点检；不返回内容） ────────


@router.get("/{account_id}/secret-path")
def get_secret_path(
    account_id: int,
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    """仅返回密钥文件应当落在哪里 + 是否存在；不读出内容。"""
    sf = get_session_factory()
    with sf() as session:
        row = session.query(AIEmployeeAccount).filter(AIEmployeeAccount.id == account_id).first()
        if not row:
            raise HTTPException(404, "账号不存在")
        target = secret_path_for(row.platform, int(row.id))
        return {
            "id": int(row.id),
            "expected_path": str(target),
            "stored_path": row.secrets_path or "",
            "exists": target.exists(),
        }


__all__ = ["router", "lookup_active_account_for"]
