"""租户 / 会话级工作区偏好（跨设备同步 SSOT）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request

from app.infrastructure.auth.dependencies import session_id_from_request
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

WORKSPACE_PREFS_KEY = "workspace_prefs"

ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "selected_industry_id",
        "industry_mod_id",
        "workflow_ai_employees",
        "product_flow_completed",
        "host_pack_acknowledged",
    }
)


def _safe_positive_int(raw: Any) -> int | None:
    try:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        val = int(text)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def resolve_workspace_owner_id(request: Request, user: Any) -> str | None:
    """优先 tenant 维度；无 tenant 时回退 session 用户维度。"""
    sid = session_id_from_request(request)
    meta: dict[str, Any] = {}
    if sid and user is not None:
        try:
            from app.application.session_account_meta import enrich_session_meta_with_tenant

            meta = enrich_session_meta_with_tenant(sid, user)
        except RECOVERABLE_ERRORS:
            logger.exception("resolve_workspace_owner_id enrich failed")

    tid = _safe_positive_int(meta.get("tenant_id"))
    if tid is not None:
        return f"tenant:{tid}"

    uid = _safe_positive_int(getattr(user, "id", None) if user is not None else None)
    if uid is None:
        uid = _safe_positive_int(meta.get("local_user_id"))
    if uid is not None:
        return f"session:{uid}"
    return None


def get_workspace_prefs(owner_id: str) -> dict[str, Any]:
    owner = str(owner_id or "").strip()
    if not owner:
        return {}
    try:
        from app.services.user_preference_service import get_user_preference_service

        raw = get_user_preference_service().get_preference(owner, WORKSPACE_PREFS_KEY)
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except RECOVERABLE_ERRORS:
        logger.exception("get_workspace_prefs failed owner=%s", owner)
        return {}


def _save_workspace_prefs(owner_id: str, prefs: dict[str, Any]) -> None:
    owner = str(owner_id or "").strip()
    if not owner:
        return
    from app.services.user_preference_service import get_user_preference_service

    get_user_preference_service().set_preference(
        owner,
        WORKSPACE_PREFS_KEY,
        json.dumps(prefs, ensure_ascii=False),
    )


def patch_workspace_prefs(owner_id: str, partial: dict[str, Any]) -> dict[str, Any]:
    """浅合并顶层字段；workflow_ai_employees 做 dict 合并。"""
    owner = str(owner_id or "").strip()
    if not owner:
        return {}
    current = get_workspace_prefs(owner)
    merged = dict(current)

    for key, value in (partial or {}).items():
        if key not in ALLOWED_TOP_LEVEL_KEYS:
            continue
        if key == "workflow_ai_employees" and isinstance(value, dict):
            wae = dict(merged.get("workflow_ai_employees") or {})
            for emp_id, enabled in value.items():
                eid = str(emp_id or "").strip()
                if not eid:
                    continue
                if isinstance(enabled, bool):
                    wae[eid] = enabled
            merged["workflow_ai_employees"] = wae
        else:
            merged[key] = value

    _save_workspace_prefs(owner, merged)
    return merged


def get_selected_industry_id(owner_id: str | None) -> str | None:
    if not owner_id:
        return None
    prefs = get_workspace_prefs(owner_id)
    raw = prefs.get("selected_industry_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def save_selected_industry(
    owner_id: str, industry_id: str, *, industry_mod_id: str = ""
) -> dict[str, Any]:
    """保存选中的行业 id（已废弃，no-op）。

    行业上下文现由 IndustryContextMiddleware 每请求从 User.industry_id 注入，
    不再持久化到 workspace_prefs。此函数保留仅为向后兼容，调用时发出
    DeprecationWarning，不再写入存储，返回空 dict。
    """
    import warnings

    warnings.warn(
        "tenant_workspace_prefs.save_selected_industry is deprecated and is now a no-op; "
        "industry context is injected per-request from User.industry_id.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.debug(
        "save_selected_industry(owner=%s, industry=%s) called but is now a no-op (readonly SSOT)",
        owner_id,
        industry_id,
    )
    return {}


__all__ = [
    "WORKSPACE_PREFS_KEY",
    "get_selected_industry_id",
    "get_workspace_prefs",
    "patch_workspace_prefs",
    "resolve_workspace_owner_id",
    "save_selected_industry",
]
