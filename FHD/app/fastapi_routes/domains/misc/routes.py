"""
XCAGI 前端兼容 API — 系统 / 认证 / 偏好 / 工具目录等杂项路由。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.domain.ai.tools_directory import get_tool_categories_payload, get_tools_payload
from app.infrastructure.auth.db_token import (
    configured_db_write_token,
    effective_db_read_token,
)
from app.infrastructure.db.sync_engine import (
    get_db_status,
    resolve_mode,
    switch_to_production_mode,
    switch_to_test_mode,
)

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)


@router.post("/fhd/db-write-token/verify")
def fhd_db_write_token_verify(body: dict = Body(default_factory=dict)) -> dict:
    expected = configured_db_write_token()
    if not expected:
        return {"success": True, "valid": True, "write_token_required": False}
    tok = str(body.get("token") or "").strip()
    return {"success": True, "valid": tok == expected, "write_token_required": True}


@router.post("/fhd/db-read-token/verify")
def fhd_db_read_token_verify(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    from app.fastapi_routes.domains.conversation.helpers import (
        _CHAT_DB_READ_GRACE_SEC,
        _touch_chat_db_read_grace,
    )

    expected = effective_db_read_token()
    if not expected:
        return {"success": True, "valid": True, "read_token_required": False, "grace_seconds": 0}
    tok = str(body.get("token") or "").strip()
    ok = tok == expected
    if ok:
        _touch_chat_db_read_grace(request)
    return {
        "success": True,
        "valid": ok,
        "read_token_required": True,
        "grace_seconds": _CHAT_DB_READ_GRACE_SEC if ok else 0,
    }


# 行业接口由 ``app.fastapi_routes.system_routes`` 提供（须在 xcagi_compat 之前注册）。
# 此处若再挂 ``/system/industry*`` 会与真实路由重复并在部分匹配顺序下导致 404。


@router.get("/system/openapi")
def system_openapi(request: Request) -> dict:
    return request.app.openapi()


def _test_db_toggle_from_body(body: dict) -> bool | None:
    for key in (
        "enabled",
        "enable",
        "on",
        "test_mode",
        "test_db_enabled",
        "testDbEnabled",
        "value",
    ):
        if key not in body:
            continue
        v = body[key]
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(int(v))
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off"):
                return False
    return None


def _compat_current_db_display_label(info: dict) -> str:
    mode = info["mode"]
    if info.get("backend") == "postgresql":
        summ = info.get("postgresql_summary") or {}
        dbn = str(summ.get("database_name") or "").strip()
        hp = str(summ.get("host_port") or "").strip()
        if dbn and hp:
            core = f"{dbn} @ {hp}"
        else:
            core = dbn or hp or "PostgreSQL"
        return f"{core}（PostgreSQL · 与 XCAGI / Mod 共用 DATABASE_URL）"
    return f"{info['current_db_name']}（{'测试' if mode == 'test' else '真实'}）"


@router.get("/system/test-db/status")
@router.get("/system/test-db/status/", include_in_schema=False)
def system_test_db_status() -> dict:
    info = get_db_status()
    mode = info["mode"]
    label = _compat_current_db_display_label(info)
    return {
        "success": True,
        "data": {
            "enabled": mode == "test",
            "test_mode": mode == "test",
            "test_db_enabled": mode == "test",
            "current_db_display": label,
            **info,
        },
    }


@router.post("/system/test-db/enable")
@router.post("/system/test-db/enable/", include_in_schema=False)
def system_test_db_enable(body: dict | None = Body(default=None)) -> dict:
    body = body if isinstance(body, dict) else {}
    want = _test_db_toggle_from_body(body)
    if want is None:
        want = resolve_mode() == "production"
    if want:
        result = switch_to_test_mode()
    else:
        result = switch_to_production_mode()
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result.get("message", str(result)))
    info = get_db_status()
    label = _compat_current_db_display_label(info)
    return {
        "success": True,
        "data": {
            "enabled": info["mode"] == "test",
            "test_mode": info["mode"] == "test",
            "test_db_enabled": info["mode"] == "test",
            "current_db_display": label,
            **info,
            "switch": result,
        },
    }


@router.post("/system/test-db/disable")
@router.post("/system/test-db/disable/", include_in_schema=False)
async def system_test_db_disable(body: dict | None = Body(default=None)) -> dict:
    merged: dict = dict(body) if isinstance(body, dict) else {}
    merged["enabled"] = False
    merged["test_db_enabled"] = False
    return system_test_db_enable(merged)


@router.get("/preferences")
@router.get("/preferences/", include_in_schema=False)
def preferences_get(user_id: str = Query(default="default")) -> dict:
    return {
        "success": True,
        "data": {"user_id": user_id, "preferences": {}},
    }


@router.post("/preferences")
@router.post("/preferences/", include_in_schema=False)
def preferences_post(body: dict = Body(default_factory=dict)) -> dict:
    return {"success": True, "data": body or {}}


def _memory_v2_service():
    from app.services.user_memory_service import get_user_memory_service

    return get_user_memory_service()


def _memory_v2_error(payload: dict, status_code: int = 400) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code)


def _memory_v2_agent_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _memory_v2_user_id_from_request(request: Request, params: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or params.get("user_id")
        or params.get("userId")
        or "default"
    ).strip()


def _run_memory_v2_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
    failure_status: int,
) -> JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    data = dict(params or {})
    user_id = _memory_v2_user_id_from_request(request, data)
    data.setdefault("user_id", user_id)
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("memory_v2") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return JSONResponse(
            {"success": False, "message": f"未注册的 Memory v2 动作: {action}"},
            status_code=400,
        )

    node_id = f"memory_v2_{action}"
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 memory_v2.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="memory_v2",
                action=action,
                params=data,
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute memory_v2.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "memory_v2_route", "route": route_path},
    )
    runtime_context = {
        "source": "memory_v2_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"Memory v2 {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "memory-v2-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    payload = _memory_v2_agent_output(run, node_id)
    status_code = 200 if payload.get("success") else failure_status
    if payload.get("error_code") == "tool_exception":
        status_code = 500
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return JSONResponse(payload, status_code=status_code)


@router.get("/memory/v2")
@router.get("/memory/v2/", include_in_schema=False)
def memory_v2_list(
    user_id: str = Query(default="default"),
    status: str | None = Query(default=None),
    memory_type: str | None = Query(default=None),
):
    try:
        svc = _memory_v2_service()
        records = svc.list_memories(user_id, status=status, memory_type=memory_type)
        return {
            "success": True,
            "user_id": user_id,
            "memories": records,
            "summary": svc.get_memory_v2_summary(user_id),
        }
    except ValueError as exc:
        return _memory_v2_error({"success": False, "message": str(exc)}, 400)


@router.get("/memory/v2/summary")
@router.get("/memory/v2/summary/", include_in_schema=False)
def memory_v2_summary(user_id: str = Query(default="default")) -> dict:
    svc = _memory_v2_service()
    return {
        "success": True,
        "user_id": user_id,
        "summary": svc.get_memory_v2_summary(user_id),
        "planner_context": svc.format_memory_v2_for_prompt(user_id),
    }


@router.post("/memory/v2/candidates")
@router.post("/memory/v2/candidates/", include_in_schema=False)
def memory_v2_create_candidate(request: Request, body: dict = Body(default_factory=dict)):
    return _run_memory_v2_agent(
        request=request,
        action="propose_candidate",
        params=dict(body or {}),
        route_path="/memory/v2/candidates",
        failure_status=400,
    )


@router.post("/memory/v2/{memory_id}/confirm")
def memory_v2_confirm(
    memory_id: str,
    request: Request,
    body: dict = Body(default_factory=dict),
):
    data = dict(body or {})
    data["memory_id"] = memory_id
    return _run_memory_v2_agent(
        request=request,
        action="confirm",
        params=data,
        route_path="/memory/v2/{memory_id}/confirm",
        failure_status=404,
    )


@router.post("/memory/v2/{memory_id}/reject")
def memory_v2_reject(
    memory_id: str,
    request: Request,
    body: dict = Body(default_factory=dict),
):
    data = dict(body or {})
    data["memory_id"] = memory_id
    return _run_memory_v2_agent(
        request=request,
        action="reject",
        params=data,
        route_path="/memory/v2/{memory_id}/reject",
        failure_status=404,
    )


@router.patch("/memory/v2/{memory_id}")
def memory_v2_correct(
    memory_id: str,
    request: Request,
    body: dict = Body(default_factory=dict),
):
    data = dict(body or {})
    data["memory_id"] = memory_id
    return _run_memory_v2_agent(
        request=request,
        action="correct",
        params=data,
        route_path="/memory/v2/{memory_id}",
        failure_status=404,
    )


@router.delete("/memory/v2/{memory_id}")
def memory_v2_delete(
    memory_id: str,
    request: Request,
    user_id: str = Query(default="default"),
    reason: str = Query(default=""),
):
    return _run_memory_v2_agent(
        request=request,
        action="delete",
        params={"user_id": user_id, "memory_id": memory_id, "reason": reason},
        route_path="/memory/v2/{memory_id}",
        failure_status=404,
    )


@router.get("/distillation/versions")
@router.get("/distillation/versions/", include_in_schema=False)
def distillation_versions() -> dict:
    return {"success": True, "data": []}


def _intent_packages_list_payload() -> dict:
    return {"success": True, "data": []}


@router.get("/intent-packages", operation_id="compat_intent_packages_hyphen")
def compat_intent_packages_hyphen() -> dict:
    return _intent_packages_list_payload()


@router.get(
    "/intent-packages/", operation_id="compat_intent_packages_hyphen_slash", include_in_schema=False
)
def compat_intent_packages_hyphen_slash() -> dict:
    return _intent_packages_list_payload()


@router.get(
    "/intent_packages", operation_id="compat_intent_packages_underscore", include_in_schema=False
)
def compat_intent_packages_underscore() -> dict:
    return _intent_packages_list_payload()


@router.get(
    "/intent_packages/",
    operation_id="compat_intent_packages_underscore_slash",
    include_in_schema=False,
)
def compat_intent_packages_underscore_slash() -> dict:
    return _intent_packages_list_payload()


@router.get("/tools", summary="工具表目录（与 XCAGI ToolsView / pro-mode 对齐）")
@router.get("/tools/", summary="工具表目录（尾斜杠）", include_in_schema=False)
def compat_tools_list(role: str | None = Query(default=None)) -> dict:
    payload = get_tools_payload()
    if role:
        tools = payload.get("tools") or []
        filtered = [t for t in tools if not t.get("roles") or role in t.get("roles", [])]
        payload = {**payload, "tools": filtered}
    return payload


@router.get("/db-tools", summary="工具表目录别名（前端优先请求）")
@router.get("/db-tools/", summary="工具表目录别名（尾斜杠）", include_in_schema=False)
def compat_db_tools_list(role: str | None = Query(default=None)) -> dict:
    payload = get_tools_payload()
    if role:
        tools = payload.get("tools") or []
        filtered = [t for t in tools if not t.get("roles") or role in t.get("roles", [])]
        payload = {**payload, "tools": filtered}
    return payload


@router.get("/tool-categories", summary="工具分类列表")
@router.get("/tool-categories/", summary="工具分类列表（尾斜杠）", include_in_schema=False)
def compat_tool_categories_list() -> dict:
    return get_tool_categories_payload()


# ========== Butler Profile（拟人 Persy 系统）==========


def _butler_profile_service():
    from app.db import SessionLocal
    from app.services.butler_profile_service import ButlerProfileService

    db = SessionLocal()
    return ButlerProfileService(db)


def _resolve_user_id_int(request: Request, body: dict | None = None) -> int:
    """从请求头或 body 解析用户 ID（整数）。默认 1。"""
    raw = (
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or (body or {}).get("user_id")
        or (body or {}).get("userId")
        or "1"
    )
    try:
        return int(str(raw).strip() or "1")
    except (TypeError, ValueError):
        return 1


def _persona_backed_profile_view(uid: int) -> dict:
    """方案 B（桥接合并）：persona_profile 为单一真相源。

    存在 persona 画像（用户已对话过）则派生 butler 视图，使 Settings UI 与对话流
    展示同一人格；尚无画像时回退 butler 自身默认视图。响应形状与 ``to_public_dict``
    严格一致，前端零改动。
    """
    try:
        from app.application.persona_butler_bridge import persona_view_for_user

        view = persona_view_for_user(uid)
        if view is not None:
            return view
    except Exception as exc:  # noqa: BLE001 - 桥接失败不应阻断 Settings 读取
        logger.warning("persona 派生 butler 视图失败，回退 butler 默认: %s", exc)
    return _butler_profile_service().get_profile_view(uid)


@router.get("/butler/profile")
@router.get("/butler/profile/", include_in_schema=False)
def butler_profile_get(
    request: Request,
    user_id: str = Query(default="1"),
) -> dict:
    """读取当前用户的 butler profile（身份 + 四轴，不含 MBTI 原始分数）。"""
    try:
        uid = _resolve_user_id_int(request, {"user_id": user_id})
        view = _persona_backed_profile_view(uid)
        return {"success": True, "profile": view}
    except Exception as exc:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.warning("读取 butler profile 失败: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"读取 profile 失败: {exc}"},
            status_code=500,
        )


@router.post("/butler/profile/infer")
@router.post("/butler/profile/infer/", include_in_schema=False)
def butler_profile_infer(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    """刷新人格视图（**人格系统已合并：Persona-A 为单一真相源**）。

    历史上此端点跑 butler MBTI 推断并写 ``butler_user_profiles``。人格合并后，对话流
    （``build_prompt_from_message`` → ``update_on_message``）已在**每条消息**上持续更新
    persona 画像，故本端点**不再独立推断 / 写 butler**，仅返回 persona 派生视图
    （无画像时回退默认）。Body 中 conversations / mod_hints 已由对话流持续吸收，
    无需在此重复喂入（避免 rapport 双计）。
    """
    try:
        uid = _resolve_user_id_int(request, body)
        view = _persona_backed_profile_view(uid)
        return {
            "success": True,
            "profile": view,
            "inference": {
                "mbti_type": view.get("mbti_type", ""),
                "identity_changed": False,
                "confidence": float(view.get("mbti_confidence") or 0.0),
                "reasons": ["人格由对话流持续学习；MBTI 为四轴展示派生，不写回"],
                "source": "persona",
            },
        }
    except Exception as exc:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.warning("butler profile 刷新失败: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"刷新失败: {exc}"},
            status_code=500,
        )


@router.post("/butler/profile/interaction")
@router.post("/butler/profile/interaction/", include_in_schema=False)
def butler_profile_record_interaction(
    request: Request, body: dict = Body(default_factory=dict)
) -> dict:
    """记录一次对话互动（**人格系统已合并：互动由对话流唯一记录**）。

    历史上此端点写 ``butler_user_profiles`` 的 rapport/互动计数。人格合并后，互动信号
    统一由 SSE 对话流（``update_on_message``）喂入 persona（单一真相源）；为避免双写双计，
    本端点**不再独立写 butler**，仅保留以兼容前端既有调用。

    Body（兼容旧契约，现仅用于校验）：user_message / assistant_message / interrupted / corrected
    """
    try:
        _resolve_user_id_int(request, body)  # 保持用户解析/错误语义
        return {"success": True, "source": "persona"}
    except Exception as exc:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.warning("记录 butler 互动失败: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"记录互动失败: {exc}"},
            status_code=500,
        )


# /api/market/llm-catalog 仅由 app.fastapi_routes.market_account 提供（见 register_all_routes 中优先挂载）。
