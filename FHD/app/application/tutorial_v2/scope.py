"""Resolve an HttpOnly tutorial run cookie into a safe business tenant scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.application.tutorial_v2.catalog import COURSE_BY_ID
from app.db.models.tutorial import TutorialRun, TutorialWorkspace

TUTORIAL_COOKIE = "xcagi_tutorial_run"
COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60


def validated_tutorial_tenant_id(request: Request) -> int | None:
    if getattr(request.state, "tutorial_active", False) is not True:
        return None
    tenant_id = getattr(request.state, "tenant_id", None)
    return int(tenant_id) if tenant_id is not None else None


_CONTROL_PREFIXES = (
    "/api/tutorial/v2",
    "/api/auth",
    "/api/login",
    "/api/logout",
    "/api/session",
    "/api/preferences",
    "/api/update",
    "/api/system",
    "/api/desktop",
    "/api/xcmax",
    "/api/license",
    "/api/admin",
    "/health",
    "/api/health",
)
_RECOVERY_PREFIXES = (
    "/login",
    "/register",
    "/forgot-account",
    "/forgot-password",
    "/api/auth",
    "/api/login",
    "/api/logout",
    "/api/session",
    "/api/tutorial/v2",
)
_EXTERNAL_OR_PRODUCTION_PREFIXES = (
    "/api/im",
    "/api/payments",
    "/api/payment",
    "/api/print",
    "/api/printer",
    "/api/connectors",
    "/api/mod-store",
    "/api/settings",
    "/api/internal-im",
    "/api/employee-im",
    "/api/etl/targets",
)
_READ_BUSINESS_PREFIXES = (
    "/api/agent",
    "/api/conversations",
    "/api/chat",
    "/api/ai/chat",
    "/api/ai/unified_chat",
    "/api/mod/xcagi-planner-bridge/chat",
    "/api/mod/xcagi-planner-bridge/unified_chat",
    "/api/mod/xcagi-erp-domain-bridge",
    "/api/mod/xcagi-approval-bridge",
    "/api/approval",
    "/api/etl",
    "/api/products",
    "/products",
    "/customers",
    "/api/customers",
    "/api/orders",
    "/api/sales",
    "/api/inventory",
    "/api/finance",
    "/api/ai/kitten",
)
_COURSE_WRITE_PREFIXES = {
    "task-workspace": (
        "/api/agent",
        "/api/chat",
        "/api/ai/chat",
        "/api/ai/unified_chat",
        "/api/mod/xcagi-planner-bridge/chat",
        "/api/mod/xcagi-planner-bridge/unified_chat",
        "/api/conversations",
    ),
    "master-data": (
        "/api/products",
        "/products",
        "/customers",
        "/api/customers",
        "/api/mod/xcagi-erp-domain-bridge/products",
        "/api/mod/xcagi-erp-domain-bridge/customers",
    ),
    "sales-to-cash": (
        "/api/agent",
        "/api/chat",
        "/api/ai/chat",
        "/api/ai/unified_chat",
        "/api/mod/xcagi-planner-bridge/chat",
        "/api/mod/xcagi-planner-bridge/unified_chat",
        "/api/conversations",
        "/api/approval",
        "/api/mod/xcagi-approval-bridge",
    ),
    "data-import": ("/api/etl", "/api/platform-shell/office-sample-upload"),
    "evidence-trace": (),
}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class TutorialScopeDecision:
    active: bool = False
    tutorial_tenant_id: int | None = None
    run_id: str | None = None
    workspace_id: str | None = None
    course_id: str | None = None
    error_code: str | None = None
    error_hint: str | None = None
    error_status: int = 409
    switched: bool = False


def _starts(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def is_tutorial_recovery_path(path: str) -> bool:
    """Return whether a stale tutorial cookie must never block this route."""
    normalized = str(path or "/").rstrip("/") or "/"
    return _starts(normalized, _RECOVERY_PREFIXES)


def resolve_tutorial_scope(
    db: Session,
    request: Request,
    *,
    user_id: int,
    source_tenant_id: int,
) -> TutorialScopeDecision:
    cookie_run_id = str(request.cookies.get(TUTORIAL_COOKIE) or "").strip()
    if not cookie_run_id:
        return TutorialScopeDecision()
    run = (
        db.query(TutorialRun)
        .filter(
            TutorialRun.id == cookie_run_id,
            TutorialRun.user_id == int(user_id),
            TutorialRun.source_tenant_id == int(source_tenant_id),
        )
        .first()
    )
    if run is None:
        return TutorialScopeDecision(
            error_code="tutorial_cookie_invalid",
            error_hint="教学会话无效，请从进阶教程重新进入。",
            error_status=401,
        )
    course = COURSE_BY_ID.get(str(run.course_id))
    if course is None or int(run.version) != int(course["version"]):
        return TutorialScopeDecision(
            error_code="tutorial_cookie_expired",
            error_hint="教程内容已升级，请从课程目录开始新版课程。",
            error_status=409,
        )
    workspace = (
        db.query(TutorialWorkspace)
        .filter(
            TutorialWorkspace.id == run.workspace_id,
            TutorialWorkspace.status == "active",
            TutorialWorkspace.user_id == int(user_id),
            TutorialWorkspace.source_tenant_id == int(source_tenant_id),
        )
        .first()
    )
    if workspace is None or run.status not in {"active", "paused", "completed"}:
        return TutorialScopeDecision(
            error_code="tutorial_cookie_expired",
            error_hint="教学会话已结束或被重置，请重新进入。",
            error_status=409,
        )
    entered = run.last_entered_at or run.started_at or run.created_at
    if entered is not None and entered < datetime.utcnow() - timedelta(
        seconds=COOKIE_MAX_AGE_SECONDS
    ):
        return TutorialScopeDecision(
            error_code="tutorial_cookie_expired",
            error_hint="教学会话已过期，请重新进入。",
            error_status=401,
        )

    path = request.url.path.rstrip("/") or "/"
    method = request.method.upper()
    base = TutorialScopeDecision(
        active=True,
        tutorial_tenant_id=int(workspace.tutorial_tenant_id),
        run_id=run.id,
        workspace_id=workspace.id,
        course_id=run.course_id,
    )
    if _starts(path, _CONTROL_PREFIXES):
        return base
    if _starts(path, _EXTERNAL_OR_PRODUCTION_PREFIXES):
        if method not in _SAFE_METHODS:
            return TutorialScopeDecision(
                **{
                    **base.__dict__,
                    "error_code": "tutorial_scope_denied",
                    "error_hint": "教学空间禁止调用真实外部能力或修改系统配置。",
                    "error_status": 403,
                }
            )
        return base
    if method in _SAFE_METHODS and _starts(path, _READ_BUSINESS_PREFIXES):
        return TutorialScopeDecision(**{**base.__dict__, "switched": True})
    if run.status == "completed" and method not in _SAFE_METHODS:
        return TutorialScopeDecision(
            **{
                **base.__dict__,
                "error_code": "tutorial_scope_denied",
                "error_hint": "复习模式仅允许查看证据；如需重新操作，请重置课程。",
                "error_status": 403,
            }
        )
    write_prefixes = _COURSE_WRITE_PREFIXES.get(run.course_id, ())
    if method not in _SAFE_METHODS and _starts(path, write_prefixes):
        return TutorialScopeDecision(**{**base.__dict__, "switched": True})
    if method not in _SAFE_METHODS:
        return TutorialScopeDecision(
            **{
                **base.__dict__,
                "error_code": "tutorial_scope_denied",
                "error_hint": "当前课程不允许执行这项写操作。",
                "error_status": 403,
            }
        )
    return base


__all__ = [
    "COOKIE_MAX_AGE_SECONDS",
    "TUTORIAL_COOKIE",
    "TutorialScopeDecision",
    "is_tutorial_recovery_path",
    "resolve_tutorial_scope",
]
