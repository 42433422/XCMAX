"""AdminRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.application.mobile_extensions.protocols import (
    AdminEmployeeItemsCall,
    CompactTextCall,
    ImServiceCall,
    LoadMarketAiEmployeeProfileIndexCall,
    MobilePrincipal,
    MobileRequestUserIdCall,
    ModstoreAdminProxyCall,
    ModstoreAdminTokenCall,
    ModstorePlatformBaseCall,
    RequireMobileAdminCall,
    SessionFactoryCall,
    UserDependency,
)
from app.fastapi_routes.mobile_extensions.constants import ADMIN_MOBILE_FEATURES
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminRoutesPorts:
    client: Callable[[float], httpx.AsyncClient]
    admin_employee_items: AdminEmployeeItemsCall
    load_market_ai_employee_profile_index: LoadMarketAiEmployeeProfileIndexCall
    mobile_request_user_id: MobileRequestUserIdCall
    require_mobile_admin: RequireMobileAdminCall
    im_service: ImServiceCall
    session_factory: SessionFactoryCall
    compact_text: CompactTextCall
    modstore_admin_token: ModstoreAdminTokenCall
    modstore_platform_base: ModstorePlatformBaseCall
    modstore_admin_proxy: ModstoreAdminProxyCall


class AdminRoutes:
    def __init__(self, ports: AdminRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/admin/employees", response_model=None)
        async def mobile_admin_employees(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            (
                market_profiles,
                market_connected,
                market_error,
            ) = await ports.load_market_ai_employee_profile_index()
            uid = ports.mobile_request_user_id(request, user)
            im_summary: dict[str, dict[str, Any]] = {}
            if uid > 0:
                try:
                    db = ports.session_factory()
                    try:
                        raw_items = ports.admin_employee_items(
                            market_profiles, market_connected=market_connected
                        )
                        im_summary = ports.im_service(db).employee_im_summary(uid, raw_items)
                    finally:
                        db.close()
                except RECOVERABLE_ERRORS:
                    logger.debug("employee_im_summary skipped for /admin/employees", exc_info=True)
            items = ports.admin_employee_items(
                market_profiles, market_connected=market_connected, im_summary=im_summary
            )
            return format_mobile_response(
                data={
                    "items": items,
                    "count": len(items),
                    "market_connected": market_connected,
                    "market_profile_count": len(market_profiles),
                    "market_error": market_error,
                }
            )

        self.mobile_admin_employees = mobile_admin_employees

        @router.get("/admin/features", response_model=None)
        async def mobile_admin_features(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            return format_mobile_response(
                data={
                    "items": ADMIN_MOBILE_FEATURES,
                    "count": len(ADMIN_MOBILE_FEATURES),
                }
            )

        self.mobile_admin_features = mobile_admin_features

        @router.get("/admin/home", response_model=None)
        async def mobile_admin_home(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            meta, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            (
                market_profiles,
                market_connected,
                market_error,
            ) = await ports.load_market_ai_employee_profile_index()
            employees = ports.admin_employee_items(
                market_profiles, market_connected=market_connected
            )
            uid = ports.mobile_request_user_id(request, user)
            im_summary: dict[str, dict[str, Any]] = {}
            if uid > 0 and employees:
                try:
                    db = ports.session_factory()
                    try:
                        im_summary = ports.im_service(db).employee_im_summary(uid, employees)
                    finally:
                        db.close()
                except RECOVERABLE_ERRORS:
                    logger.debug("employee_im_summary skipped", exc_info=True)
            employees = ports.admin_employee_items(
                market_profiles, market_connected=market_connected, im_summary=im_summary
            )
            return format_mobile_response(
                data={
                    "account_kind": meta.get("account_kind") or "admin",
                    "employees": employees,
                    "employee_count": len(employees),
                    "features": ADMIN_MOBILE_FEATURES,
                    "feature_count": len(ADMIN_MOBILE_FEATURES),
                    "market_connected": market_connected,
                    "market_profile_count": len(market_profiles),
                    "market_error": market_error,
                }
            )

        self.mobile_admin_home = mobile_admin_home

        def _modstore_platform_base() -> str:
            """获取 MODstore 后端 base url（如 http://127.0.0.1:8765）。"""
            return os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000").rstrip("/")

        self._modstore_platform_base = _modstore_platform_base

        def _modstore_admin_token() -> str:
            """获取调 MODstore admin API 用的 Bearer token。"""
            return os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()

        self._modstore_admin_token = _modstore_admin_token

        async def _modstore_admin_proxy(
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
            json_body: dict[str, Any] | None = None,
            timeout: float = 10.0,
        ) -> dict[str, Any]:
            """通用代理：调 MODstore 后端 admin API。

            返回 {"ok": bool, "status": int, "data": ..., "error": str}。
            """
            url = f"{ports.modstore_platform_base()}{path}"
            headers = {"Accept": "application/json"}
            token = ports.modstore_admin_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with ports.client(timeout) as client:
                    resp = await client.request(
                        method, url, params=params, json=json_body, headers=headers
                    )
                try:
                    data = resp.json()
                except RECOVERABLE_ERRORS:
                    data = {"raw": resp.text[:500]}
                if resp.is_success:
                    return {"ok": True, "status": resp.status_code, "data": data}
                return {
                    "ok": False,
                    "status": resp.status_code,
                    "error": str(data.get("detail") or data.get("error") or resp.text[:200])[:300],
                }
            except RECOVERABLE_ERRORS as exc:
                return {
                    "ok": False,
                    "status": 0,
                    "error": f"无法连接 MODstore 后端：{ports.compact_text(exc)[:200]}",
                }

        self._modstore_admin_proxy = _modstore_admin_proxy

        @router.get("/admin/employee-pending-questions", response_model=None)
        async def mobile_admin_employee_pending_questions(
            request: Request,
            limit: int = Query(default=50, ge=1, le=200),
            include_history: bool = Query(default=False),
            employee_id: str | None = Query(default=None),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """拉员工 Phase-D 主动提问列表（pending 优先）。

            GET /api/mobile/v1/admin/employee-pending-questions
              ?limit=50&include_history=false&employee_id=llm-ops-engineer

            返回 {"items": [...], "count": N, "market_connected": bool}
            每个 item 含：id / employee_id / task / question / status / asked_at / answer / answered_at
            """
            meta, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            params: dict[str, Any] = {
                "limit": limit,
                "include_expired": bool(include_history),
            }
            if employee_id:
                params["employee_id"] = employee_id
            out = await ports.modstore_admin_proxy(
                "GET", "/api/admin/employee-autonomy/questions", params=params
            )
            if not out.get("ok"):
                return format_mobile_response(
                    None,
                    f"拉员工提问失败：{out.get('error') or '未知错误'}",
                    success=False,
                    code=out.get("status") or 502,
                )
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            if not isinstance(data, dict):
                data = {}
            items = data.get("items") if isinstance(data.get("items"), list) else []
            return format_mobile_response(
                data={
                    "items": items,
                    "count": int(data.get("count") or len(items or [])),
                    "market_connected": bool(out.get("ok")),
                }
            )

        self.mobile_admin_employee_pending_questions = mobile_admin_employee_pending_questions

        @router.post("/admin/employee-pending-questions/{question_id}/answer", response_model=None)
        async def mobile_admin_employee_pending_question_answer(
            question_id: int,
            body: dict[str, Any],
            request: Request,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """老板回答员工的 Phase-D 提问。

            POST /api/mobile/v1/admin/employee-pending-questions/{id}/answer
            body: {"answer": "先做 A，因为..."}

            成功后员工执行管道被阻塞的 ask_human_blocking() 会拿到答案继续执行。
            """
            meta, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            answer_text = str((body or {}).get("answer") or "").strip()
            if not answer_text:
                return format_mobile_response(None, "answer 字段不能为空", success=False, code=400)
            out = await ports.modstore_admin_proxy(
                "POST",
                f"/api/admin/employee-autonomy/questions/{int(question_id)}/answer",
                json_body={"answer": answer_text},
            )
            if not out.get("ok"):
                return format_mobile_response(
                    None,
                    f"回答失败：{out.get('error') or '未知错误'}",
                    success=False,
                    code=out.get("status") or 502,
                )
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            return format_mobile_response(data=data)

        self.mobile_admin_employee_pending_question_answer = (
            mobile_admin_employee_pending_question_answer
        )
