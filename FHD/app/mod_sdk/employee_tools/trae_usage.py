"""Trae usage projections with explicit home directory and HTTP boundary."""

from __future__ import annotations

import json

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .employee_tool_ports import Payload, TraePorts
from .results import _ok


async def query_trae_usage(ports: TraePorts, params: Payload, ctx: Payload) -> Payload:
    """查询 Trae IDE 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.trae-cn/trae-jwt-token → 尝试调 Trae API 获取 token 用量
    2. Trae CN/User/globalStorage/state.vscdb — 聊天轮次、模型列表、用户 ID
    3. ~/.trae-cn/ 目录 — 配置文件

    注意：Trae 的 token 用量 API 被 403 拦截（需要网页 cookie），
    本工具能提取聊天轮次、模型列表、当前模型等本地数据。
    """
    import sqlite3

    trae_cn = ports.home / ".trae-cn"
    trae_app = ports.home / "Library" / "Application Support" / "Trae CN"
    result_data: Payload = {
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
            resp = ports.get(
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
        except RECOVERABLE_ERRORS as exc:
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
                    current_models = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
            cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
            row = cur.fetchone()
            available_models = {}
            if row:
                try:
                    available_models = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
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
                    for mode, models in available_models.items()
                },
                "feedback_keys": list(feedback.keys()),
            }
        except RECOVERABLE_ERRORS as exc:
            result_data["local_state"] = {"error": str(exc)}
    argv_file = trae_cn / "argv.json"
    if argv_file.is_file():
        result_data["sources"].append("argv.json")
        try:
            result_data["config"] = {"argv": json.loads(argv_file.read_text(encoding="utf-8"))}
        except RECOVERABLE_ERRORS:
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
    return _ok(
        f"Trae 使用统计：{local.get('accumulated_chat_turns', 0)} 轮聊天，{len(result_data['sources'])} 个数据源",
        **result_data,
    )
