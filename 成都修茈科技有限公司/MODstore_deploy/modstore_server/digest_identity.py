"""每日摘要「身份校验码」：解析 HTML、规范化输入、与修茈市场管理端解锁同一套校验口径。

XCmax 前端应优先调用 ``GET /api/xcmax/admin/digest-identity`` 展示身份码，避免与
``POST /api/auth/verify-admin-digest-code`` 各自解析 HTML 导致不一致。
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.models import DailyDigestRecord, OpsApprovalToken

DIGEST_IDENTITY_HTML_RE = re.compile(
    r"身份校验码[\s\S]*?<code[^>]*>([0-9A-Fa-f]{6})</code>",
    re.IGNORECASE,
)


def normalize_digest_identity_code(raw: str) -> str:
    """去掉邮件客户端插入的空格/连字符，并转成大写十六进制。"""
    return re.sub(r"[\s-]+", "", raw or "").upper()


def extract_digest_identity_plain_from_html(html: str) -> str:
    """从摘要 HTML 中取出 6 位身份校验码（与历史前端正则一致）。"""
    m = DIGEST_IDENTITY_HTML_RE.search(html or "")
    return m.group(1).upper() if m else ""


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def verify_digest_identity(session: Session, raw_code: str, *, now: datetime | None = None) -> str:
    """与 ``market_auth_api.api_verify_admin_digest_code`` 相同逻辑：有效则返回 UTC ISO 过期时间，否则返回空串。

    ``raw_code`` 应为已规范化或待规范化的用户输入；内部会再次 ``normalize_digest_identity_code``。
    """
    code = normalize_digest_identity_code(raw_code or "")
    if len(code) != 6 or any(c not in "0123456789ABCDEF" for c in code):
        return ""

    th = hashlib.sha256(code.encode("utf-8")).hexdigest()
    ttl_hours = int(os.environ.get("MODSTORE_APPROVAL_TOKEN_TTL_HOURS", "36"))
    now_ = now or datetime.now(timezone.utc)

    tok = (
        session.query(OpsApprovalToken)
        .filter(
            OpsApprovalToken.kind == "digest_identity",
            OpsApprovalToken.token_hash == th,
            OpsApprovalToken.expires_at > now_,
        )
        .order_by(OpsApprovalToken.id.desc())
        .first()
    )
    if tok:
        exp = _as_utc_aware(tok.expires_at)
        return exp.isoformat() if exp else ""

    rows = session.query(DailyDigestRecord).order_by(DailyDigestRecord.id.desc()).limit(20).all()
    for row in rows:
        plain = extract_digest_identity_plain_from_html(row.body_html or "")
        if plain != code:
            continue
        created = _as_utc_aware(row.created_at)
        if created is None or created > now_:
            continue
        digest_expires = created + timedelta(hours=ttl_hours)
        if digest_expires <= now_:
            continue
        return digest_expires.isoformat()

    return ""


def resolve_digest_identity_for_xcmax(session: Session) -> dict[str, Any]:
    """供 XCmax ``GET /api/xcmax/admin/digest-identity``：返回当前宜展示的码及是否与解锁校验一致。"""
    rows = session.query(DailyDigestRecord).order_by(DailyDigestRecord.id.desc()).limit(12).all()
    for row in rows:
        plain = extract_digest_identity_plain_from_html(row.body_html or "")
        if not plain:
            continue
        exp = verify_digest_identity(session, plain)
        if exp:
            return {
                "code": plain,
                "expires_at": exp,
                "valid": True,
                "daily_digest_id": int(row.id),
            }

    latest = rows[0] if rows else None
    plain_latest = extract_digest_identity_plain_from_html(latest.body_html or "") if latest else ""
    return {
        "code": plain_latest or "",
        "expires_at": "",
        "valid": False,
        "daily_digest_id": int(latest.id) if latest else None,
    }
