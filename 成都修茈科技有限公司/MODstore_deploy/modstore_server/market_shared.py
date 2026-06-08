"""XC AGI 在线市场共享常量、辅助函数与依赖别名。"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import (
    CatalogItem,
    Entitlement,
    LandingContactSubmission,
    User,
    VerificationCode,
    get_session_factory,
)

_get_current_user = get_current_user
_require_admin = require_admin

MATERIAL_CATEGORY_LABELS = {
    "ai_employee": "AI 员工",
    "agent_prompt": "Agent 提示词",
    "skill": "Skill",
    "tts_voice": "TTS 声音模型",
    "mod_asset": "MOD 包素材",
    "page_style": "页面风格",
    "personal_design": "个性化设计",
    "workflow_template": "工作流模板",
    "other": "其他素材",
}

LICENSE_SCOPE_LABELS = {
    "personal": "个人使用",
    "commercial": "商业授权",
    "free_personal": "免费个人用",
    "enterprise": "企业级",
}

RISKY_ORIGIN_TYPES = {"derivative", "collaboration", "fan_linkage", "suspected_plagiarism"}
RISKY_IP_LEVELS = {"medium", "high"}

_CONTACT_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CONTACT_SUBMIT_TIMES: dict[str, list[float]] = defaultdict(list)
_CONTACT_SUBMIT_LIMIT = int(os.environ.get("MODSTORE_PUBLIC_CONTACT_LIMIT", "10"))
_CONTACT_SUBMIT_WINDOW_SEC = int(os.environ.get("MODSTORE_PUBLIC_CONTACT_WINDOW_SEC", "3600"))

# 公司名联网匹配：只读、可略频繁，与表单提交分开计数
_CONTACT_MATCH_TIMES: dict[str, list[float]] = defaultdict(list)
_CONTACT_MATCH_LIMIT = int(os.environ.get("MODSTORE_PUBLIC_CONTACT_MATCH_LIMIT", "40"))
_CONTACT_MATCH_WINDOW_SEC = int(os.environ.get("MODSTORE_PUBLIC_CONTACT_MATCH_WINDOW_SEC", "600"))

_WORKBENCH_MATCH_TIMES: dict[str, list[float]] = defaultdict(list)
_WORKBENCH_MATCH_LIMIT = int(os.environ.get("MODSTORE_WORKBENCH_COMPANY_MATCH_LIMIT", "80"))
_WORKBENCH_MATCH_WINDOW_SEC = int(
    os.environ.get("MODSTORE_WORKBENCH_COMPANY_MATCH_WINDOW_SEC", "600")
)


def _optional_current_user(authorization: Optional[str] = Header(None)) -> Optional[User]:
    if not authorization:
        return None
    try:
        return _get_current_user(authorization)
    except HTTPException:
        return None


def _normalize_material_category(raw: str | None, artifact: str | None = None) -> str:
    value = (raw or "").strip()
    if value in MATERIAL_CATEGORY_LABELS:
        return value
    art = (artifact or "").strip()
    if art == "employee_pack":
        return "ai_employee"
    if art == "workflow_template":
        return "workflow_template"
    if art == "surface":
        return "page_style"
    if art == "bundle":
        return "mod_asset"
    if art == "mod":
        return "mod_asset"
    return "other"


def _normalize_license_scope(raw: str | None, price: float = 0.0) -> str:
    value = (raw or "").strip()
    if value in LICENSE_SCOPE_LABELS:
        return value
    return "commercial" if float(price or 0) > 0 else "personal"


def _normalize_origin_type(raw: str | None) -> str:
    value = (raw or "").strip()
    return value or "original"


def _normalize_ip_risk_level(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    return value if value in {"low", "medium", "high"} else "low"


def _effective_license_scope(item: CatalogItem) -> str:
    return _normalize_license_scope(getattr(item, "license_scope", None), float(item.price or 0))


def _ensure_catalog_listing_allowed(
    *,
    price: float,
    license_scope: str,
    origin_type: str,
    ip_risk_level: str,
) -> None:
    paid = float(price or 0) > 0
    if paid and license_scope != "commercial":
        raise HTTPException(400, "收费商品必须选择商业授权")
    if origin_type in RISKY_ORIGIN_TYPES or ip_risk_level in RISKY_IP_LEVELS:
        if paid or license_scope == "commercial":
            raise HTTPException(400, "疑似抄袭、二创、联动或中高风险素材只能免费或限制个人使用")


def _entitlement_metadata(item: CatalogItem, source: str) -> str:
    return json.dumps(
        {
            "source": source,
            "license_scope": _effective_license_scope(item),
            "material_category": _normalize_material_category(
                getattr(item, "material_category", None),
                getattr(item, "artifact", None),
            ),
            "origin_type": _normalize_origin_type(getattr(item, "origin_type", None)),
            "ip_risk_level": _normalize_ip_risk_level(getattr(item, "ip_risk_level", None)),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _catalog_item_payload(
    item: CatalogItem,
    *,
    purchased: bool = False,
    favorited: bool = False,
    favorite_count: int = 0,
    user_has_review: bool = False,
    complaint_count: int = 0,
) -> Dict[str, Any]:
    material_category = _normalize_material_category(
        getattr(item, "material_category", None),
        getattr(item, "artifact", None),
    )
    license_scope = _effective_license_scope(item)
    return {
        "id": item.id,
        "pkg_id": item.pkg_id,
        "version": item.version,
        "name": item.name,
        "description": item.description,
        "price": float(item.price or 0),
        "artifact": item.artifact,
        "material_category": material_category,
        "material_category_label": MATERIAL_CATEGORY_LABELS.get(
            material_category, material_category
        ),
        "license_scope": license_scope,
        "license_scope_label": LICENSE_SCOPE_LABELS.get(license_scope, license_scope),
        "origin_type": _normalize_origin_type(getattr(item, "origin_type", None)),
        "ip_risk_level": _normalize_ip_risk_level(getattr(item, "ip_risk_level", None)),
        "compliance_status": getattr(item, "compliance_status", None) or "approved",
        "rank_score": float(getattr(item, "rank_score", 100.0) or 0),
        "delist_reason": getattr(item, "delist_reason", None) or "",
        "industry": getattr(item, "industry", None) or "通用",
        "security_level": getattr(item, "security_level", None) or "personal",
        "author_id": item.author_id,
        "purchased": purchased,
        "favorited": favorited,
        "favorite_count": max(0, int(favorite_count or 0)),
        "user_has_review": user_has_review,
        "complaint_count": complaint_count,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


def _grant_catalog_entitlement(
    session,
    *,
    user_id: int,
    item: CatalogItem,
    source: str,
    source_order_id: str = "",
) -> None:
    ent_type = "employee" if (item.artifact or "") == "employee_pack" else "mod"
    existing = (
        session.query(Entitlement)
        .filter(
            Entitlement.user_id == user_id,
            Entitlement.catalog_id == item.id,
            Entitlement.is_active == True,
        )
        .first()
    )
    if existing:
        existing.metadata_json = _entitlement_metadata(item, source)
        if source_order_id:
            existing.source_order_id = source_order_id
        return
    session.add(
        Entitlement(
            user_id=user_id,
            catalog_id=item.id,
            entitlement_type=ent_type,
            source_order_id=source_order_id,
            metadata_json=_entitlement_metadata(item, source),
            granted_at=datetime.now(timezone.utc),
            is_active=True,
        )
    )


def _public_contact_client_key(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:128] or "unknown"
    if request.client and request.client.host:
        return request.client.host[:128]
    return "unknown"


def _public_contact_rate_allow(key: str) -> None:
    now = time.time()
    cutoff = now - _CONTACT_SUBMIT_WINDOW_SEC
    bucket = _CONTACT_SUBMIT_TIMES[key]
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _CONTACT_SUBMIT_LIMIT:
        raise HTTPException(status_code=429, detail="提交过于频繁，请稍后再试")
    bucket.append(now)


def _public_contact_company_match_rate_allow(key: str) -> None:
    """联系页公司匹配专用限流（不与表单提交共用配额）。"""
    now = time.time()
    cutoff = now - _CONTACT_MATCH_WINDOW_SEC
    bucket = _CONTACT_MATCH_TIMES[key]
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _CONTACT_MATCH_LIMIT:
        raise HTTPException(status_code=429, detail="匹配请求过于频繁，请稍后再试")
    bucket.append(now)


def _workbench_company_match_rate_allow(key: str) -> None:
    """工作台联网公司匹配：已登录用户单独计数，配额略高于公开联系页。"""
    now = time.time()
    cutoff = now - _WORKBENCH_MATCH_WINDOW_SEC
    bucket = _WORKBENCH_MATCH_TIMES[key]
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _WORKBENCH_MATCH_LIMIT:
        raise HTTPException(status_code=429, detail="联网搜索过于频繁，请稍后再试")
    bucket.append(now)
