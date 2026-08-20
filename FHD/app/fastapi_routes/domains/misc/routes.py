"""
XCAGI 前端兼容 API — 系统 / 认证 / 偏好 / 工具目录等杂项路由。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.domain.ai.tools_directory import (
    get_tool_categories_payload,
    get_tools_payload,
    register_workflow_tool_registry_provider,
)
from app.fastapi_routes.domains.misc import memory_v2_agent as _memory_agent
from app.fastapi_routes.domains.misc.persona_route_helpers import resolve_persona_user_id
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
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _workflow_tool_registry_provider() -> list[dict]:
    """组装注入：domain 工具目录经本门面惰性访问 application 层 workflow 注册表。"""
    from app.application.tools.workflow import get_workflow_tool_registry

    return get_workflow_tool_registry()


register_workflow_tool_registry_provider(_workflow_tool_registry_provider)

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)

_memory_v2_agent_output = _memory_agent.agent_output
_memory_v2_user_id_from_request = _memory_agent.user_id_from_request
_run_memory_v2_agent = _memory_agent.run_memory_v2_agent
_resolve_persona_user_id = resolve_persona_user_id
_resolve_user_id_int = resolve_persona_user_id


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
    return cast("dict[Any, Any]", request.app.openapi())


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
    from app.application.memory_v2_facade import get_user_memory_service

    return get_user_memory_service()


def _memory_v2_error(payload: dict, status_code: int = 400) -> JSONResponse:
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
    except ValueError:
        return _memory_v2_error({"success": False, "message": "记忆查询参数无效"}, 400)


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


def _persona_backed_profile_view(uid: int | str) -> dict:
    """人格视图的**唯一派生路径**：Persona-A → butler 视图（经 persona_butler_bridge）。

    有画像派生其画像；无画像（新用户）派生中性默认——两者走完全相同的桥逻辑。
    **不再回退 butler 自身 ``get_profile_view``/``derive_mbti``**，确保 MBTI/四轴
    只有桥这一处派生源（单一真相源 + 自动派生）。响应形状与 ``to_public_dict`` 一致。
    """
    from app.application.persona_butler_bridge import persona_default_view, persona_view_for_user

    key = str(uid).strip() or "1"
    try:
        view = persona_view_for_user(key)
        if view is not None:
            return view
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - 桥接失败不应阻断 Settings 读取
        logger.warning("persona 画像读取失败，回退 persona 默认视图: %s", exc)
    return persona_default_view(key)


@router.get("/butler/profile", response_model=None)
@router.get("/butler/profile/", response_model=None, include_in_schema=False)
def butler_profile_get(
    request: Request,
    user_id: str = Query(default="1"),
) -> dict[str, Any] | JSONResponse:
    """读取当前用户的 butler profile（身份 + 四轴，不含 MBTI 原始分数）。"""
    try:
        uid = _resolve_user_id_int(request, {"user_id": user_id})
        view = _persona_backed_profile_view(uid)
        return {"success": True, "profile": view}
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.exception("读取 butler profile 失败")
        return JSONResponse(
            {"success": False, "message": "读取 profile 失败"},
            status_code=500,
        )


@router.post("/butler/profile/infer", response_model=None)
@router.post("/butler/profile/infer/", response_model=None, include_in_schema=False)
def butler_profile_infer(
    request: Request, body: dict = Body(default_factory=dict)
) -> dict[str, Any] | JSONResponse:
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
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.exception("butler profile 刷新失败")
        return JSONResponse(
            {"success": False, "message": "刷新失败"},
            status_code=500,
        )


@router.post("/butler/profile/interaction", response_model=None)
@router.post("/butler/profile/interaction/", response_model=None, include_in_schema=False)
def butler_profile_record_interaction(
    request: Request, body: dict = Body(default_factory=dict)
) -> dict[str, Any] | JSONResponse:
    """记录一次对话互动（**人格系统已合并：互动由对话流唯一记录**）。

    历史上此端点写 ``butler_user_profiles`` 的 rapport/互动计数。人格合并后，互动信号
    统一由 SSE 对话流（``update_on_message``）喂入 persona（单一真相源）；为避免双写双计，
    本端点**不再独立写 butler**，仅保留以兼容前端既有调用。

    Body（兼容旧契约，现仅用于校验）：user_message / assistant_message / interrupted / corrected
    """
    try:
        _resolve_user_id_int(request, body)  # 保持用户解析/错误语义
        return {"success": True, "source": "persona"}
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 路由边界统一兜底返回 JSON
        logger.exception("记录 butler 互动失败")
        return JSONResponse(
            {"success": False, "message": "记录互动失败"},
            status_code=500,
        )


# /api/market/llm-catalog 仅由 app.fastapi_routes.market_account 提供（见 register_all_routes 中优先挂载）。
