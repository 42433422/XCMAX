"""开发者密钥 Web→桌面加密导出（ECDH P-256 + AES-GCM）与审计。"""

from __future__ import annotations

import base64
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.auth_service import generate_pat, hash_pat, verify_password
from modstore_server.datetime_utils import as_utc_aware
from modstore_server.infrastructure.db import get_db
from modstore_server.key_export_crypto import encrypt_json_to_recipient
from modstore_server.models import DeveloperKeyExportEvent, DeveloperToken, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/developer/key-export", tags=["developer", "key-export"])

# 每用户滑动窗口内最大导出次数
_EXPORT_WINDOW = timedelta(minutes=15)
_EXPORT_MAX_PER_WINDOW = 8
# 单次最多包含的 Token 条数
_MAX_TOKENS_IN_BUNDLE = 12

_rate_buckets: Dict[int, Deque[datetime]] = {}


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return ""


def _rate_check(user_id: int) -> None:
    now = datetime.now(timezone.utc)
    dq = _rate_buckets.setdefault(user_id, deque())
    while dq and now - dq[0] > _EXPORT_WINDOW:
        dq.popleft()
    if len(dq) >= _EXPORT_MAX_PER_WINDOW:
        raise HTTPException(429, "导出过于频繁，请稍后再试")
    dq.append(now)


def _audit(
    db: Session,
    *,
    user_id: int,
    client_ip: str,
    user_agent: str,
    action: str,
    token_ids: List[int],
    success: bool,
    detail: str,
    algorithm: str = "",
) -> None:
    row = DeveloperKeyExportEvent(
        user_id=user_id,
        client_ip=client_ip[:64],
        user_agent=(user_agent or "")[:512],
        action=action[:64],
        token_ids_json=json.dumps(token_ids, ensure_ascii=False),
        token_count=len(token_ids),
        success=success,
        detail=(detail or "")[:512],
        algorithm=(algorithm or "")[:64],
    )
    db.add(row)


class ExportBundleBody(BaseModel):
    """桌面端生成 P-256 公钥（DER SPKI）后 base64 传入；须验证登录密码。"""

    recipient_public_key_spki_b64: str = Field(..., min_length=32, max_length=4096)
    current_password: str = Field(..., min_length=1, max_length=256)
    token_ids: List[int] = Field(..., min_length=1, max_length=_MAX_TOKENS_IN_BUNDLE)
    rotate_source_tokens: bool = Field(
        default=True,
        description="为 True 时吊销所选旧 Token 并以同名同 scope 签发新明文，仅出现在加密包内",
    )

    @field_validator("token_ids")
    @classmethod
    def unique_ids(cls, v: List[int]) -> List[int]:
        seen = set()
        out: List[int] = []
        for i in v:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out


@router.post("/bundle", summary="加密导出 PAT 包到桌面公钥（须密码确认；默认轮换所选 Token）")
def export_encrypted_bundle(
    body: ExportBundleBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    try:
        spki = base64.b64decode(body.recipient_public_key_spki_b64.strip())
    except Exception as e:
        raise HTTPException(400, "recipient_public_key_spki_b64 不是合法 base64") from e
    if len(spki) < 32:
        raise HTTPException(400, "公钥过短")

    _rate_check(user.id)

    row_user = db.query(User).filter(User.id == user.id).first()
    if not row_user or not verify_password(body.current_password, row_user.password_hash):
        _audit(
            db,
            user_id=user.id,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent") or "",
            action="key_bundle_export",
            token_ids=body.token_ids,
            success=False,
            detail="password_mismatch",
        )
        db.commit()
        raise HTTPException(403, "当前密码错误")

    if not body.rotate_source_tokens:
        _audit(
            db,
            user_id=user.id,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent") or "",
            action="key_bundle_export",
            token_ids=body.token_ids,
            success=False,
            detail="rotate_required",
        )
        db.commit()
        raise HTTPException(
            400,
            "未携带明文 PAT 时无法导出；请使用 rotate_source_tokens=true（将轮换所选 Token 并仅出现在加密包中）",
        )

    olds: List[DeveloperToken] = []
    for tid in body.token_ids:
        r = (
            db.query(DeveloperToken)
            .filter(DeveloperToken.id == tid, DeveloperToken.user_id == user.id)
            .first()
        )
        if not r:
            raise HTTPException(404, f"Token id={tid} 不存在")
        if r.revoked_at is not None:
            raise HTTPException(400, f"Token id={tid} 已吊销")
        exp = as_utc_aware(r.expires_at)
        if exp and exp < datetime.now(timezone.utc):
            raise HTTPException(400, f"Token id={tid} 已过期")
        olds.append(r)

    now = datetime.now(timezone.utc)
    new_rows: List[Tuple[DeveloperToken, str, DeveloperToken, List[Any]]] = []
    for old in olds:
        raw, prefix, digest = generate_pat()
        try:
            scopes = json.loads(old.scopes_json or "[]")
            if not isinstance(scopes, list):
                scopes = []
        except json.JSONDecodeError:
            scopes = []
        exp = old.expires_at
        nr = DeveloperToken(
            user_id=user.id,
            name=(old.name or "").strip() or "imported",
            token_prefix=prefix,
            token_hash=digest,
            scopes_json=json.dumps(scopes, ensure_ascii=False),
            expires_at=exp,
        )
        db.add(nr)
        new_rows.append((nr, raw, old, scopes))

    try:
        db.flush()
    except Exception:
        db.rollback()
        raise

    issued: List[Dict[str, Any]] = []
    for nr, raw, old, scopes in new_rows:
        issued.append(
            {
                "replaced_id": old.id,
                "id": nr.id,
                "name": nr.name,
                "prefix": nr.token_prefix,
                "token": raw,
                "scopes": scopes,
            }
        )

    payload = {
        "v": 1,
        "issued_at": now.isoformat() + "Z",
        "algorithm": "ECDH_SECP256R1_AES256GCM",
        "tokens": issued,
    }
    plain = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        blob = encrypt_json_to_recipient(spki, plain)
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        db.rollback()
        logger.exception("key export encrypt failed")
        raise HTTPException(400, f"加密失败: {e}") from e

    for old in olds:
        old.revoked_at = now

    _audit(
        db,
        user_id=user.id,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent") or "",
        action="key_bundle_export",
        token_ids=body.token_ids,
        success=True,
        detail="ok",
        algorithm="ECDH_SECP256R1_AES256GCM",
    )
    db.commit()

    return {
        "algorithm": "ECDH_SECP256R1_AES256GCM",
        "cipher_b64": base64.b64encode(blob).decode("ascii"),
        "expires_in_seconds": int(_EXPORT_WINDOW.total_seconds()),
        "token_count": len(issued),
        "rotated_ids": body.token_ids,
    }


@router.get("/audit", summary="当前用户最近的密钥导出审计记录")
def list_export_audit(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    lim = max(1, min(limit, 200))
    rows = (
        db.query(DeveloperKeyExportEvent)
        .filter(DeveloperKeyExportEvent.user_id == user.id)
        .order_by(DeveloperKeyExportEvent.id.desc())
        .limit(lim)
        .all()
    )
    out = []
    for r in rows:
        try:
            ids = json.loads(r.token_ids_json or "[]")
        except json.JSONDecodeError:
            ids = []
        out.append(
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "client_ip": r.client_ip,
                "action": r.action,
                "token_ids": ids if isinstance(ids, list) else [],
                "token_count": r.token_count,
                "success": r.success,
                "detail": r.detail,
                "algorithm": r.algorithm,
            }
        )
    return {"events": out}
