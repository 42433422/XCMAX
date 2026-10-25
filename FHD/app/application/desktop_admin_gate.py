"""桌面进程级禁止管理员会话与管理端 API（管理端仅网页 SSOT）。

凡 ``is_desktop_mode()==True`` 的后端进程一律禁 admin，与请求来自 Electron
或系统浏览器无关。
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DESKTOP_ADMIN_FORBIDDEN_MESSAGE = "桌面端不支持管理员账号登录，请使用网页版管理端"
DESKTOP_ADMIN_FORBIDDEN_CODE = "ADMIN_DESKTOP_FORBIDDEN"

# 桌面进程上直接拒绝的管理端 API 前缀（双保险；具体路由仍应调用会话门禁）
DESKTOP_ADMIN_API_PREFIXES: tuple[str, ...] = (
    "/api/xcmax/admin",
    "/api/admin",
    "/api/mobile/v1/admin",
)


def is_desktop_runtime() -> bool:
    try:
        from app.utils.deployment import is_desktop_mode

        return bool(is_desktop_mode())
    except RECOVERABLE_ERRORS:
        return False


def is_admin_account_kind(account_kind: Any) -> bool:
    return str(account_kind or "").strip().lower() in {"admin", "admin_portal"}


def forbidden_payload() -> dict[str, Any]:
    return {
        "success": False,
        "message": DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
        "error": {
            "code": DESKTOP_ADMIN_FORBIDDEN_CODE,
            "message": DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
        },
        "valid": False,
    }


def delete_session_quiet(session_id: str | None) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    try:
        from app.infrastructure.session import get_session_manager

        get_session_manager().delete_session(sid)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop admin gate: delete_session failed: %s", exc)


def assert_desktop_allows_session(
    meta: dict[str, Any] | None,
    *,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """若桌面进程且会话为 admin：删会话并返回 forbidden payload；否则 None。"""
    if not is_desktop_runtime():
        return None
    kind = None
    if isinstance(meta, dict):
        kind = meta.get("account_kind")
    if not is_admin_account_kind(kind):
        return None
    delete_session_quiet(session_id)
    return forbidden_payload()


def assert_desktop_allows_session_id(session_id: str | None) -> dict[str, Any] | None:
    """按 session_id 加载 meta 后执行 ``assert_desktop_allows_session``。"""
    if not is_desktop_runtime():
        return None
    sid = str(session_id or "").strip()
    if not sid:
        return None
    try:
        from app.application.session_account_meta import load_session_account_meta

        meta = load_session_account_meta(sid) or {}
    except RECOVERABLE_ERRORS:
        meta = {}
    return assert_desktop_allows_session(meta, session_id=sid)


def reject_admin_on_desktop(
    *,
    session_id: str | None,
    account_kind: str | None,
) -> dict[str, Any] | None:
    """登录流用：已知 account_kind 时拒绝并删会话。"""
    return assert_desktop_allows_session(
        {"account_kind": account_kind},
        session_id=session_id,
    )


def is_desktop_admin_api_path(path: str) -> bool:
    p = str(path or "").strip()
    if not p:
        return False
    for prefix in DESKTOP_ADMIN_API_PREFIXES:
        if p == prefix or p.startswith(prefix + "/"):
            return True
    return False


def purge_admin_sessions_on_desktop() -> int:
    """启动时一次性清除本地 DB 中 account_kind=admin 的会话行。返回删除条数。"""
    if not is_desktop_runtime():
        return 0
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_host_db

        with get_host_db() as db:
            rows = (
                db.query(UserSession)
                .filter(UserSession.account_kind.in_(("admin", "admin_portal")))
                .all()
            )
            count = 0
            for row in rows:
                sid = str(getattr(row, "session_id", "") or "").strip()
                db.delete(row)
                count += 1
                if sid:
                    try:
                        from app.infrastructure.session import get_session_manager

                        get_session_manager().delete_session(sid)
                    except RECOVERABLE_ERRORS:
                        pass
            if count:
                db.commit()
                logger.info("desktop admin gate: purged %d admin session row(s)", count)
            return count
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop admin gate: purge admin sessions skipped: %s", exc)
        return 0
