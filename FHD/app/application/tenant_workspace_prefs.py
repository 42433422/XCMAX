"""租户 / 会话级工作区偏好（跨设备同步 SSOT）。"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

from fastapi import Request

from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

WORKSPACE_PREFS_KEY = "workspace_prefs"
WORKSPACE_PREFS_REVISION_KEY = "_revision"
ENTERPRISE_LEVEL_KEY = "enterprise_intelligence_level"
ENTERPRISE_MODEL_KEY = "enterprise_model"


@contextmanager
def _workspace_base_db_scope():
    """Preferences are host-owned even when a mobile or Mod route is active.

    Only the preference DB operation is routed to the host. Restore the Mod
    context immediately so downstream enterprise business reads keep their
    original scope and authorization decisions.
    """
    from app.request_active_mod_ctx import (
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    token = set_request_active_mod_id("")
    try:
        yield
    finally:
        reset_request_active_mod_id(token)


class WorkspacePrefsVersionConflict(ValueError):
    """The client edited a stale workspace snapshot; reload before retrying."""


def workspace_prefs_revision(value: dict[str, Any]) -> int:
    """Unversioned legacy preferences begin at revision zero."""
    revision = value.get(WORKSPACE_PREFS_REVISION_KEY, 0)
    if type(revision) is not int or revision < 0:
        raise ValueError("Invalid persisted workspace preferences revision")
    return revision


ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "selected_industry_id",
        "industry_mod_id",
        "workflow_ai_employees",
        "product_flow_completed",
        "host_pack_acknowledged",
        "onboarding_completed_at",
        "onboarding_seed_done",
        "onboarding_ai_demo_done",
        ENTERPRISE_LEVEL_KEY,
        ENTERPRISE_MODEL_KEY,
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


def session_workspace_owner_id(request: Request) -> str | None:
    user = resolve_session_user(request)
    return resolve_workspace_owner_id(request, user) if user is not None else None


def get_workspace_prefs(owner_id: str, *, strict: bool = False) -> dict[str, Any]:
    owner = str(owner_id or "").strip()
    if not owner:
        return {}
    try:
        from app.domain.shared_services.user_preference_service import get_user_preference_service

        with _workspace_base_db_scope():
            raw = get_user_preference_service().get_preference(owner, WORKSPACE_PREFS_KEY)
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        if strict:
            raise ValueError("Workspace preferences must contain a JSON object")
        return {}
    except RECOVERABLE_ERRORS:
        if strict:
            raise
        logger.exception("get_workspace_prefs failed owner=%s", owner)
        return {}


def enterprise_intelligence_scope(user: Any) -> tuple[str, bool] | None:
    """Only an active enterprise's authenticated members may read its mode."""
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.db.session import get_host_db

    tid = _safe_positive_int(getattr(user, "tenant_id", None))
    if tid is None or getattr(user, "role", None) == "admin":
        return None
    with get_host_db() as db:
        tenant = (
            db.query(Tenant.owner_user_id)
            .join(User, User.id == Tenant.owner_user_id)
            .filter(
                Tenant.id == tid,
                Tenant.is_active.is_(True),
                User.is_active.is_(True),
                User.tenant_id == tid,
                User.tier == "enterprise",
            )
            .one_or_none()
        )
    return (f"tenant:{tid}", tenant.owner_user_id == user.id) if tenant is not None else None


def workspace_intelligence_level(prefs: dict[str, Any]) -> int | None:
    level = prefs.get(ENTERPRISE_LEVEL_KEY)
    if level is not None and (type(level) is not int or not 1 <= level <= 6):
        raise ValueError("Invalid persisted enterprise intelligence level")
    return level


def workspace_model_choice(prefs: dict[str, Any]) -> tuple[str, str, str] | None:
    value = prefs.get(ENTERPRISE_MODEL_KEY)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid persisted enterprise model")
    provider, model, key_source = (value.get(key) for key in ("provider", "model", "key_source"))
    if not (
        isinstance(provider, str)
        and provider
        and isinstance(model, str)
        and model
        and isinstance(key_source, str)
        and key_source
    ):
        raise ValueError("Invalid persisted enterprise model")
    return provider, model, key_source


def enterprise_model_for_actor(actor_id: str) -> tuple[str, str, str] | None:
    """Read the actor's current tenant choice, including when no HTTP context exists."""
    from app.db.models.user import User
    from app.db.session import get_host_db

    with get_host_db() as db:
        actor = db.get(User, int(actor_id))
        scope = enterprise_intelligence_scope(actor) if actor and actor.is_active else None
    return workspace_model_choice(get_workspace_prefs(scope[0], strict=True)) if scope else None


_OWNER_PREF_PREFIX = "user_pref:"


def get_owner_preferences(owner_id: str) -> dict[str, str]:
    """设置页等零散键值偏好，与工作区偏好同库、按工作区归属隔离。"""
    from app.domain.shared_services.user_preference_service import get_user_preference_service

    with _workspace_base_db_scope():
        rows = get_user_preference_service().get_all_preferences(owner_id)
    n = len(_OWNER_PREF_PREFIX)
    return {k[n:]: v for k, v in rows.items() if k.startswith(_OWNER_PREF_PREFIX)}


def set_owner_preference(owner_id: str, key: str, value: str) -> None:
    from app.domain.shared_services.user_preference_service import get_user_preference_service

    with _workspace_base_db_scope():
        get_user_preference_service().set_preference(owner_id, _OWNER_PREF_PREFIX + key, value)


def workspace_owner_id_from_user(user: Any) -> str | None:
    """Resolve the persisted workspace owner for a DB-backed user object."""
    tid = _safe_positive_int(getattr(user, "tenant_id", None) if user is not None else None)
    if tid is not None:
        return f"tenant:{tid}"
    uid = _safe_positive_int(getattr(user, "id", None) if user is not None else None)
    if uid is not None:
        return f"session:{uid}"
    return None


def _industry_mod_id_for_workspace(industry_id: str, explicit_mod_id: str = "") -> str:
    iid = str(industry_id or "").strip()
    mid = str(explicit_mod_id or "").strip()
    if mid or not iid:
        return mid
    try:
        from app.mod_sdk.industry_seed import industry_mod_id_for

        mid = str(industry_mod_id_for(iid) or "").strip()
        if mid:
            return mid
    except RECOVERABLE_ERRORS:
        logger.exception("industry_mod_id_for failed for industry=%s", iid)
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id_for_industry

        return str(canonical_mod_id_for_industry(iid) or "").strip()
    except RECOVERABLE_ERRORS:
        logger.exception("canonical_mod_id_for_industry failed for industry=%s", iid)
        return ""


def patch_workspace_prefs(
    owner_id: str,
    partial: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Merge fields atomically; optional revision token fences stale clients."""
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise ValueError("Invalid expected workspace preferences revision")
    owner = str(owner_id or "").strip()
    if not owner:
        return {}
    from app.domain.shared_services.user_preference_service import get_user_preference_service

    def merge(raw: str | None) -> str:
        current = json.loads(raw) if raw is not None else {}
        if not isinstance(current, dict):
            raise ValueError("Workspace preferences must contain a JSON object")
        revision = workspace_prefs_revision(current)
        if expected_revision is not None and expected_revision != revision:
            raise WorkspacePrefsVersionConflict(
                f"workspace_prefs_version_conflict expected={expected_revision} actual={revision}"
            )
        merged = dict(current)

        for key, value in (partial or {}).items():
            if key not in ALLOWED_TOP_LEVEL_KEYS:
                continue
            if key == "workflow_ai_employees" and isinstance(value, dict):
                wae = dict(merged.get("workflow_ai_employees") or {})
                for emp_id, enabled in value.items():
                    eid = str(emp_id or "").strip()
                    if eid and isinstance(enabled, bool):
                        wae[eid] = enabled
                merged["workflow_ai_employees"] = wae
            else:
                merged[key] = value

        merged[WORKSPACE_PREFS_REVISION_KEY] = revision + 1
        return json.dumps(merged, ensure_ascii=False)

    with _workspace_base_db_scope():
        saved = get_user_preference_service().mutate_preference(owner, WORKSPACE_PREFS_KEY, merge)
    prefs = json.loads(saved)
    if not isinstance(prefs, dict):
        raise ValueError("Workspace preferences must contain a JSON object")
    return prefs


def bind_selected_industry_for_user(
    user: Any,
    industry_id: str,
    *,
    industry_mod_id: str = "",
    owner_id: str | None = None,
    persist_workspace_prefs: bool = True,
) -> dict[str, Any]:
    """Bind industry to User SSOT; optionally skip a redundant preference write."""
    iid = str(industry_id or "").strip()
    if not iid or user is None:
        return {}
    resolved_owner = str(owner_id or "").strip() or workspace_owner_id_from_user(user)
    uid = _safe_positive_int(getattr(user, "id", None))
    try:
        if uid is not None:
            from app.db.models.user import User
            from app.db.session import get_db
            from app.domain.app_pure.entitled_industries_init import (
                init_entitled_industries_for_user,
            )

            with _workspace_base_db_scope(), get_db() as db:
                db_user = db.query(User).filter(User.id == uid).first()
                if db_user is not None:
                    db_user.industry_id = iid
                    tier = str(getattr(db_user, "tier", "") or "personal").strip().lower()
                    db_user.entitled_industries = init_entitled_industries_for_user(tier, iid)
                    db.commit()
                    resolved_owner = resolved_owner or workspace_owner_id_from_user(db_user)
    except RECOVERABLE_ERRORS:
        logger.exception("bind_selected_industry_for_user user update failed uid=%s", uid)

    if not resolved_owner:
        return {}
    if not persist_workspace_prefs:
        # Caller already completed the guarded workspace preference write.
        # Reapplying it would increment its revision twice.
        return get_workspace_prefs(resolved_owner)
    partial: dict[str, Any] = {"selected_industry_id": iid}
    mid = _industry_mod_id_for_workspace(iid, industry_mod_id)
    if mid:
        partial["industry_mod_id"] = mid
    return patch_workspace_prefs(resolved_owner, partial)


def bind_selected_industry_for_username(
    username: str,
    industry_id: str,
    *,
    industry_mod_id: str = "",
) -> dict[str, Any]:
    """Registration helper: bind industry for the newly created local user."""
    uname = str(username or "").strip()
    iid = str(industry_id or "").strip()
    if not uname or not iid:
        return {}
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with _workspace_base_db_scope(), get_db() as db:
            user = db.query(User).filter(User.username == uname).first()
            if user is None:
                return {}
            return bind_selected_industry_for_user(
                user,
                iid,
                industry_mod_id=industry_mod_id,
                owner_id=workspace_owner_id_from_user(user),
            )
    except RECOVERABLE_ERRORS:
        logger.exception("bind_selected_industry_for_username failed username=%s", uname)
        return {}


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
    "WORKSPACE_PREFS_REVISION_KEY",
    "WorkspacePrefsVersionConflict",
    "workspace_prefs_revision",
    "bind_selected_industry_for_user",
    "bind_selected_industry_for_username",
    "get_selected_industry_id",
    "get_workspace_prefs",
    "patch_workspace_prefs",
    "resolve_workspace_owner_id",
    "save_selected_industry",
    "workspace_owner_id_from_user",
]
