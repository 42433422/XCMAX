"""建联后需求表单入库：自动设为企业客户并同步市场侧显示名（公司名）。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MARKET_BASE = (
    (os.environ.get("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com") or "").strip().rstrip("/")
)
_INTERNAL_KEY = (
    os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY", "")
    or os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_SECRET", "xcagi-cs-intake-dev-secret")
).strip()


def _normalize_display_name(company: str, *, fallback: str = "") -> str:
    raw = (company or fallback or "").strip()
    if not raw:
        return ""
    # 去掉常见公司后缀便于卡片展示（保留原意时可再调）
    cleaned = (
        re.sub(
            r"(有限公司|有限责任公司|股份有限公司|集团有限公司|公司)$",
            "",
            raw,
        ).strip()
        or raw
    )
    return cleaned[:64]


def ensure_enterprise_profile_from_intake(
    market_user_id: int,
    *,
    company: str = "",
    contact_name: str = "",
    min_stage: str = "connected",
) -> dict[str, Any]:
    """
    调用 MODstore internal API：is_enterprise=true + username←公司名。
    仅当 pipeline 阶段已达 min_stage（默认已建联）时由调用方触发。
    """
    uid = int(market_user_id)
    if uid <= 0:
        return {"ok": False, "skipped": True, "reason": "invalid_market_user_id"}
    if not _MARKET_BASE or not _INTERNAL_KEY:
        return {"ok": False, "skipped": True, "reason": "market_internal_not_configured"}

    display = _normalize_display_name(company, fallback=contact_name)
    url = f"{_MARKET_BASE}/api/internal/cs-intake/ensure-enterprise-profile"
    payload = {
        "market_user_id": uid,
        "company": company.strip()[:256],
        "display_name": display,
        "min_stage": min_stage,
    }
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"X-Internal-Api-Key": _INTERNAL_KEY},
            timeout=12.0,
        )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "skipped": False,
                "error": str(data.get("detail") or data.get("message") or resp.text)[:500],
                "status_code": resp.status_code,
            }
        if isinstance(data, dict) and data.get("ok"):
            return {
                "ok": True,
                "skipped": bool(data.get("skipped")),
                "reason": data.get("reason"),
                "user_id": data.get("user_id", uid),
                "username": data.get("username"),
                "is_enterprise": data.get("is_enterprise"),
                "renamed": bool(data.get("renamed")),
            }
        return {"ok": False, "error": "unexpected_market_response", "data": data}
    except Exception as exc:
        logger.exception("ensure_enterprise_profile_from_intake failed uid=%s", uid)
        return {"ok": False, "error": str(exc)[:500]}


def apply_enterprise_profile_to_pipeline_doc(
    doc: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """将市场侧回写的用户名同步进 pipeline JSON。"""
    if not profile.get("ok") or profile.get("skipped"):
        return doc
    username = str(profile.get("username") or "").strip()
    if username:
        doc["username"] = username
    if profile.get("is_enterprise"):
        from datetime import datetime, timezone

        doc["enterprise_auto_provisioned_at"] = datetime.now(timezone.utc).isoformat()
    return doc
