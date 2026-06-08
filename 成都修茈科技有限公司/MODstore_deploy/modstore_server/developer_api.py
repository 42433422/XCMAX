"""开发者凭证管理：Personal Access Token 的 CRUD。

Token 体验对齐 GitHub PAT：
- 创建时**仅一次**返回明文（``token`` 字段），客户端必须立刻保管；
- 之后只能看到掩码 prefix 与元信息，无法重新读出明文；
- 吊销采用软删除（``revoked_at``），保留审计；
- 校验路径在 ``application.auth.AuthApplicationService`` 中与 JWT 共管道。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.auth_service import generate_pat
from modstore_server.datetime_utils import as_utc_aware
from modstore_server.developer_scopes import validate_scopes_or_raise
from modstore_server.infrastructure.db import get_db
from modstore_server.models import DeveloperToken, User

router = APIRouter(prefix="/api/developer", tags=["developer"])


class CreateTokenBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: List[str] = Field(default_factory=list)
    expires_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365,
        description="可选：N 天后过期；为空则永不过期，需手动吊销",
    )


def _serialize_token(row: DeveloperToken) -> Dict[str, Any]:
    """对外列表返回结构（不含明文）。"""
    try:
        scopes = json.loads(row.scopes_json or "[]")
        if not isinstance(scopes, list):
            scopes = []
    except json.JSONDecodeError:
        scopes = []
    now = datetime.now(timezone.utc)
    expires_at = as_utc_aware(row.expires_at)
    return {
        "id": row.id,
        "name": row.name or "",
        "prefix": row.token_prefix,
        "scopes": scopes,
        "created_at": as_utc_aware(row.created_at).isoformat() if row.created_at else None,
        "last_used_at": as_utc_aware(row.last_used_at).isoformat() if row.last_used_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "revoked_at": as_utc_aware(row.revoked_at).isoformat() if row.revoked_at else None,
        "is_active": row.revoked_at is None and (expires_at is None or expires_at > now),
    }


@router.post("/tokens", summary="创建开发者 Token（明文仅返回一次）")
async def create_developer_token(
    body: CreateTokenBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    try:
        scopes_norm = validate_scopes_or_raise(body.scopes or [])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    raw, prefix, digest = generate_pat()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=int(body.expires_days))
        if body.expires_days
        else None
    )
    row = DeveloperToken(
        user_id=user.id,
        name=body.name.strip(),
        token_prefix=prefix,
        token_hash=digest,
        scopes_json=json.dumps(scopes_norm, ensure_ascii=False),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    payload = _serialize_token(row)
    payload["token"] = raw  # 仅本次返回
    return payload


@router.get("/tokens", summary="开发者 Token 列表")
async def list_developer_tokens(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(DeveloperToken)
        .filter(DeveloperToken.user_id == user.id)
        .order_by(DeveloperToken.created_at.desc())
        .all()
    )
    return [_serialize_token(r) for r in rows]


@router.delete("/tokens/{token_id}", summary="吊销开发者 Token（软删除，保留审计）")
async def revoke_developer_token(
    token_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(DeveloperToken)
        .filter(
            DeveloperToken.id == token_id,
            DeveloperToken.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Token 不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True, "id": row.id}
