# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


async def tool_query_trae_usage(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询 Trae IDE 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.trae-cn/trae-jwt-token → 尝试调 Trae API 获取 token 用量
    2. Trae CN/User/globalStorage/state.vscdb — 聊天轮次、模型列表、用户 ID
    3. ~/.trae-cn/ 目录 — 配置文件

    注意：Trae 的 token 用量 API 被 403 拦截（需要网页 cookie），
    本工具能提取聊天轮次、模型列表、当前模型等本地数据。
    """
    import sqlite3

    trae_cn = _facade().Path.home() / ".trae-cn"
    trae_app = _facade().Path.home() / "Library" / "Application Support" / "Trae CN"
    result_data: dict[str, _facade().Any] = {
        "sources": [],
        "api_usage": None,
        "local_state": None,
        "config": None,
        "trae_summary": {},
    }
    jwt_path = trae_cn / "trae-jwt-token"
    if jwt_path.is_file():
        result_data["sources"].append("trae-jwt-token")
        jwt_token = jwt_path.read_text(encoding="utf-8").strip()
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://trae.cn/api/v1/user/usage",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "User-Agent": "Trae/1.10.0",
                    "Content-Type": "application/json",
                },
                timeout=8,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                result_data["api_usage"] = resp.json()
            else:
                result_data["api_usage"] = {
                    "status_code": resp.status_code,
                    "note": f"Trae API 返回 {resp.status_code}，token 用量需去 Trae 网页设置页查看",
                }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["api_usage"] = {"error": str(exc)}
    state_db = trae_app / "User" / "globalStorage" / "state.vscdb"
    if state_db.is_file():
        result_data["sources"].append("state.vscdb")
        try:
            conn = sqlite3.connect(str(state_db))
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%'")
            feedback = {}
            for k, v in cur.fetchall():
                feedback[k] = v
            accumulated_turns = 0
            for k, v in feedback.items():
                if "accumulatedTurns" in k:
                    try:
                        accumulated_turns = int(v)
                    except (ValueError, TypeError):
                        pass
            cur.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%'"
            )
            current_models = {}
            for _k, v in cur.fetchall():
                try:
                    current_models = _facade().json.loads(v)
                except (_facade().json.JSONDecodeError, TypeError):
                    pass
            cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
            row = cur.fetchone()
            available_models = {}
            if row:
                try:
                    available_models = _facade().json.loads(row[0])
                except (_facade().json.JSONDecodeError, TypeError):
                    pass
            cur.execute(
                "SELECT key FROM ItemTable WHERE key LIKE '%_ai-chat:sessionRelation%' LIMIT 1"
            )
            user_id = ""
            row = cur.fetchone()
            if row and "_" in row[0]:
                user_id = row[0].split("_")[0]
            conn.close()
            result_data["local_state"] = {
                "user_id": user_id,
                "accumulated_chat_turns": accumulated_turns,
                "current_models": current_models,
                "available_models_by_mode": {
                    mode: [m.get("name", "") for m in models if isinstance(m, dict)]
                    for (mode, models) in available_models.items()
                },
                "feedback_keys": list(feedback.keys()),
            }
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data["local_state"] = {"error": str(exc)}
    argv_file = trae_cn / "argv.json"
    if argv_file.is_file():
        result_data["sources"].append("argv.json")
        try:
            result_data["config"] = {
                "argv": _facade().json.loads(argv_file.read_text(encoding="utf-8"))
            }
        except _facade().RECOVERABLE_ERRORS:
            pass
    local = result_data.get("local_state") or {}
    result_data["trae_summary"] = {
        "chat_turns": local.get("accumulated_chat_turns", 0),
        "current_models": local.get("current_models", {}),
        "user_id": local.get("user_id", ""),
        "api_accessible": bool(
            result_data.get("api_usage")
            and isinstance(result_data.get("api_usage"), dict)
            and ("status_code" not in result_data.get("api_usage", {}))
        ),
        "note": "Trae token 用量 API 被 403 拦截。本地能提取聊天轮次和模型列表，精确 token 用量需去 Trae 设置页查看。",
    }
    return _facade()._ok(
        f"Trae 使用统计：{local.get('accumulated_chat_turns', 0)} 轮聊天，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


def get_employee_tools(employee_id: str) -> list[str]:
    """返回某员工注册的专属工具名列表。"""
    return list(_facade().EMPLOYEE_TOOLS.get(employee_id, []))


def list_all_tool_names() -> list[str]:
    """返回全部已注册工具名。"""
    return sorted(_facade().TOOL_REGISTRY.keys())


async def handle_specialized(
    employee_id: str, payload: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """专属工具调度入口。

    payload 形如：
        {"handler": "specialized", "tool": "run_pytest", "params": {...}}
    或：
        {"handler": "specialized", "tool": "list_tools"}
    """
    tool_name = str(payload.get("tool") or "").strip()
    if not tool_name:
        available = _facade().get_employee_tools(employee_id)
        return _facade()._ok(
            f"员工 {employee_id} 可用 {len(available)} 个专属工具",
            employee_id=employee_id,
            available_tools=available,
            handler="specialized",
        )
    allowed = _facade().get_employee_tools(employee_id)
    if tool_name not in allowed:
        return _facade()._err(
            f"工具 {tool_name!r} 不在员工 {employee_id} 的专属工具清单中。可用: {allowed}",
            employee_id=employee_id,
            available_tools=allowed,
        )
    fn = _facade().TOOL_REGISTRY.get(tool_name)
    if fn is None or not callable(fn):
        return _facade()._err(f"工具 {tool_name!r} 未实现")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _facade()._err("params 必须为对象")
    if tool_name in _facade()._code_write_tools():
        gate_verdict = await _facade()._check_write_gate(employee_id, tool_name, params, ctx)
        if not gate_verdict.get("ok", True):
            return _facade()._err(
                f"写操作被 gate 拦截: {gate_verdict.get('reason', '')}",
                blocked=True,
                gate_result=gate_verdict,
                pending_approval=bool(gate_verdict.get("pending_approval")),
                approval_request_ids=list(gate_verdict.get("approval_request_ids") or []),
            )
    try:
        result = await fn(params, ctx)
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade()._err(f"工具 {tool_name!r} 执行异常: {exc!r}")
    if not isinstance(result, dict):
        return _facade()._ok(f"工具 {tool_name!r} 完成", raw=result)
    result.setdefault("tool", tool_name)
    result.setdefault("employee_id", employee_id)
    result.setdefault("handler", "specialized")
    return result
