"""移动端 API 扩展 — 管理端/市场/MOD 相关纯计算辅助函数。"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Request

from app.fastapi_routes.mobile_extensions.constants import _MARKET_AI_EMPLOYEE_CACHE

logger = logging.getLogger(__name__)


# ── 文本工具 ──


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _market_profile_text(profile: dict[str, Any], key: str) -> str:
    return _compact_text(profile.get(key))


def _market_profile_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in ("pkg_id", "id", "name"):
        value = _compact_text(row.get(key))
        if value:
            keys.append(value.lower())
    return keys


def _admin_employee_match_keys(raw: dict[str, Any], employee_id: str, name: str) -> list[str]:
    keys = [employee_id, name]
    stored = _compact_text(raw.get("stored_filename"))
    if stored:
        keys.append(stored)
        base = stored.removesuffix(".xcemp")
        keys.append(base)
        parts = base.rsplit("-", 1)
        if len(parts) == 2 and parts[1][:1].isdigit():
            keys.append(parts[0])
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip().lower()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


# ── 市场档案索引 ──


def _index_market_ai_employee_profiles(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        material = _compact_text(row.get("material_category")).lower()
        artifact = _compact_text(row.get("artifact")).lower()
        if material and material != "ai_employee":
            continue
        if artifact and artifact not in {"mod", "employee_pack", "ai_employee"}:
            continue
        for key in _market_profile_keys(row):
            out.setdefault(key, row)
    return out


async def _load_market_ai_employee_profile_index() -> tuple[dict[str, dict[str, Any]], bool, str]:
    now = time.monotonic()
    ttl = float(os.environ.get("XCAGI_MOBILE_MARKET_PROFILE_CACHE_TTL", "300") or 300)
    cached_profiles = _MARKET_AI_EMPLOYEE_CACHE.get("profiles")
    if (
        isinstance(cached_profiles, dict)
        and cached_profiles
        and now < float(_MARKET_AI_EMPLOYEE_CACHE.get("expires_at") or 0)
    ):
        return (
            cached_profiles,
            bool(_MARKET_AI_EMPLOYEE_CACHE.get("connected")),
            str(_MARKET_AI_EMPLOYEE_CACHE.get("error") or ""),
        )

    try:
        import httpx

        from app.infrastructure.mods.catalog_client import market_catalog_list_url

        timeout = float(os.environ.get("XCAGI_MOBILE_MARKET_PROFILE_TIMEOUT", "6") or 6)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                market_catalog_list_url(),
                params={"material_category": "ai_employee", "limit": 200, "offset": 0},
            )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items") if isinstance(payload, dict) else []
        profiles = _index_market_ai_employee_profiles(items if isinstance(items, list) else [])
        _MARKET_AI_EMPLOYEE_CACHE.update(
            {
                "expires_at": now + ttl,
                "profiles": profiles,
                "connected": True,
                "error": "",
            }
        )
        return profiles, True, ""
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - network availability is environment-specific
        error = _compact_text(exc)
        if isinstance(cached_profiles, dict) and cached_profiles:
            _MARKET_AI_EMPLOYEE_CACHE.update(
                {
                    "expires_at": now + min(ttl, 60),
                    "connected": False,
                    "error": error,
                }
            )
            return cached_profiles, False, error
        _MARKET_AI_EMPLOYEE_CACHE.update(
            {
                "expires_at": now + min(ttl, 60),
                "profiles": {},
                "connected": False,
                "error": error,
            }
        )
        return {}, False, error


def _apply_market_profile(
    item: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    market_connected: bool,
) -> None:
    if not profile:
        item.update(
            {
                "profile_source": "admin",
                "market_connected": False,
                "market_pkg_id": "",
                "market_name": "",
                "market_description": "",
                "market_version": "",
                "market_author": "",
                "market_industry": "",
                "market_material_category": "",
                "market_license_scope": "",
                "market_security_level": "",
                "market_avatar": "",
            }
        )
        return
    item.update(
        {
            "profile_source": "ai_market",
            "market_connected": bool(market_connected),
            "market_pkg_id": _market_profile_text(profile, "pkg_id")
            or _market_profile_text(profile, "id"),
            "market_name": _market_profile_text(profile, "name"),
            "market_description": _market_profile_text(profile, "description"),
            "market_version": _market_profile_text(profile, "version"),
            "market_author": _market_profile_text(profile, "author")
            or _market_profile_text(profile, "publisher")
            or _market_profile_text(profile, "author_id"),
            "market_industry": _market_profile_text(profile, "industry"),
            "market_material_category": _market_profile_text(profile, "material_category"),
            "market_license_scope": _market_profile_text(profile, "license_scope"),
            "market_security_level": _market_profile_text(profile, "security_level"),
            "market_avatar": _market_profile_text(profile, "avatar")
            or _market_profile_text(profile, "logo")
            or _market_profile_text(profile, "icon"),
        }
    )


# ── Duty 员工展示元数据注册表 ──


def _candidate_duty_registry_paths() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("MODSTORE_DEPLOY_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root))
    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[4] / "成都修茈科技有限公司" / "MODstore_deploy",
            Path.cwd() / "成都修茈科技有限公司" / "MODstore_deploy",
        ]
    )
    out: list[Path] = []
    for root in roots:
        out.append(root / "modstore_server" / "catalog_data" / "duty_employee_registry.json")
    return out


def _load_admin_duty_records() -> list[dict[str, Any]]:
    for path in _candidate_duty_registry_paths():
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            packages = raw.get("packages") if isinstance(raw, dict) else []
            if isinstance(packages, list):
                return [p for p in packages if isinstance(p, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("mobile admin duty registry read failed: %s", exc)
    return []


# ── MOD / 工作流员工 ──


def _employee_text(employee: Any, key: str) -> str:
    if isinstance(employee, dict):
        return _compact_text(employee.get(key))
    return _compact_text(getattr(employee, key, ""))


def _workflow_employee_match_keys(mod_id: str, employee: Any) -> list[str]:
    keys = [
        mod_id,
        _employee_text(employee, "id"),
        _employee_text(employee, "label"),
        _employee_text(employee, "name"),
        _employee_text(employee, "panel_title"),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip().lower()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _workflow_employee_to_dict(employee: Any) -> dict[str, Any]:
    if isinstance(employee, dict):
        return dict(employee)
    out: dict[str, Any] = {}
    for key in (
        "id",
        "label",
        "name",
        "panel_title",
        "panel_summary",
        "api_base_path",
        "phone_channel",
        "workflow_placeholder",
    ):
        value = getattr(employee, key, None)
        if value is not None:
            out[key] = value
    return out


def _enrich_workflow_employees(
    mod_id: str,
    employees: list[Any],
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for employee in employees:
        row = _workflow_employee_to_dict(employee)
        profile = None
        if market_profiles:
            for key in _workflow_employee_match_keys(mod_id, row):
                profile = market_profiles.get(key)
                if profile:
                    break
        _apply_market_profile(row, profile, market_connected=market_connected)
        enriched.append(row)
    return enriched


# ── 会话/鉴权辅助 ──


def _mobile_session_meta(request: Request) -> dict[str, Any]:
    from app.application.session_account_meta import load_session_account_meta
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.security.mobile_jwt import verify_mobile_jwt

    sid = ""
    jwt_meta: dict[str, Any] = {}
    authorization_raw = request.headers.get("Authorization") or ""
    authorization = authorization_raw if isinstance(authorization_raw, str) else ""
    if authorization.startswith("Bearer "):
        payload = verify_mobile_jwt(authorization[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "").strip()
            account_kind = str(payload.get("account_kind") or "").strip()
            jwt_meta = {
                "session_id": sid,
                "account_kind": account_kind,
                "market_is_admin": account_kind == "admin",
                "username": str(payload.get("username") or "").strip(),
            }
    if not sid:
        try:
            sid = session_id_from_request(request)
        except (AttributeError, TypeError):
            # Keep direct service-level callers and compatibility shims usable;
            # a real Starlette Request always exposes cookies.
            sid = ""
    if sid:
        meta = load_session_account_meta(sid)
        if meta:
            return meta
    return jwt_meta


def _require_mobile_admin(request: Request, user: Any) -> tuple[dict[str, Any], Any | None]:
    from fastapi.responses import JSONResponse

    from app.utils.mobile_api import format_mobile_response

    if user is None:
        return {}, JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    meta = _mobile_session_meta(request) or {}
    role = str(getattr(user, "role", "") or "").strip()
    jwt_or_session_admin = meta.get("account_kind") == "admin" and (
        bool(meta.get("market_is_admin")) or role in {"admin", "super_admin", "owner"}
    )
    if not jwt_or_session_admin:
        return meta, JSONResponse(
            format_mobile_response(None, "需要管理端管理员账号", success=False, code=403),
            status_code=403,
        )
    return meta, None


def _require_mobile_admin_or_enterprise(
    request: Request, user: Any
) -> tuple[dict[str, Any], Any | None]:
    """企业端 + 管理端都可访问的 Codex 超级员工专用鉴权。"""
    from fastapi.responses import JSONResponse

    from app.utils.mobile_api import format_mobile_response

    if user is None:
        return {}, JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    meta = _mobile_session_meta(request) or {}
    role = str(getattr(user, "role", "") or "").strip().lower()
    account_kind = str(meta.get("account_kind") or "").strip().lower()
    if not account_kind:
        account_kind = "enterprise" if role == "enterprise" else "personal"
    if account_kind == "enterprise":
        return meta, None
    if account_kind in {"admin", "admin_portal"} and (
        bool(meta.get("market_is_admin"))
        or role in {"admin", "admin_portal", "super_admin", "owner"}
    ):
        return meta, None
    return meta, JSONResponse(
        format_mobile_response(None, "需要管理端管理员账号", success=False, code=403),
        status_code=403,
    )


def _mobile_request_user_id(request: Request, user: Any) -> int:
    authorization_raw = request.headers.get("Authorization") or ""
    authorization = authorization_raw if isinstance(authorization_raw, str) else ""
    if authorization.startswith("Bearer "):
        try:
            from app.security.mobile_jwt import user_id_from_mobile_bearer

            uid = user_id_from_mobile_bearer(authorization)
            if uid:
                return int(uid)
        except (ImportError, ValueError, TypeError):
            pass
    for attr in ("id", "user_id"):
        try:
            uid = getattr(user, attr, None)
        except (AttributeError, TypeError):
            continue
        try:
            uid_int = int(uid or 0)
        except (TypeError, ValueError):
            uid_int = 0
        if uid_int > 0:
            return uid_int
    return 0
