"""MCP 工具接入：把外部工具并入现有注册表与风险策略。

默认无配置文件即完全停用；发现结果缓存 5 分钟，避免每轮对话拉起子进程。
外部工具沿用现有权限、风险门、审批与租户边界，不新增旁路。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.infrastructure.mcp.client import (
    RESOURCE_ACTIONS,
    McpToolInfo,
    call_tool,
    list_tools,
)
from app.infrastructure.mcp.config import McpServerConfig, load_server_configs, mcp_enabled
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "tools": {}, "servers": {}}

_SLUG = re.compile(r"[^A-Za-z0-9_]+")
_READ_ONLY_ACTIONS = (
    "get",
    "list",
    "search",
    "query",
    "read",
    "fetch",
    "describe",
    "find",
    "show",
)


def _slug(value: str) -> str:
    cleaned = _SLUG.sub("_", str(value or "").strip()).strip("_")
    return cleaned.lower() or "server"


def tool_id_for(server_name: str) -> str:
    return f"mcp__{_slug(server_name)}"


def _is_read_only(info: McpToolInfo) -> bool:
    if info.read_only:
        return True
    name = info.name.lower()
    return any(name == prefix or name.startswith(f"{prefix}_") for prefix in _READ_ONLY_ACTIONS)


_RESOURCE_ACTION_SPECS: dict[str, dict[str, Any]] = {
    "mcp_list_resources": {
        "risk": "low",
        "idempotent": True,
        "required_params": [],
        "availability": "shared",
        "description": "列出该 MCP 服务器提供的资源",
    },
    "mcp_read_resource": {
        "risk": "low",
        "idempotent": True,
        "required_params": ["uri"],
        "availability": "shared",
        "description": "读取该 MCP 服务器指定 uri 的资源",
    },
    "mcp_list_prompts": {
        "risk": "low",
        "idempotent": True,
        "required_params": [],
        "availability": "shared",
        "description": "列出该 MCP 服务器提供的提示词模板",
    },
    "mcp_get_prompt": {
        "risk": "low",
        "idempotent": True,
        "required_params": ["name"],
        "availability": "shared",
        "description": "获取该 MCP 服务器指定提示词模板",
    },
}


def _action_spec(info: McpToolInfo) -> dict[str, Any]:
    read_only = _is_read_only(info)
    schema = info.input_schema if isinstance(info.input_schema, dict) else {}
    required = schema.get("required")
    required_params = (
        [str(item) for item in required if str(item).strip()] if isinstance(required, list) else []
    )
    return {
        "risk": "low" if read_only else "high",
        "idempotent": read_only,
        "required_params": required_params,
        "availability": "shared",
        "description": info.description,
        **({} if read_only else {"requires_write_approval": True}),
    }


def _register_with_guard(tools: dict[str, Any]) -> None:
    if not tools:
        return
    try:
        from app.domain.autonomy.autonomy_guard import get_autonomy_guard

        guard = get_autonomy_guard()
        for tool_id, meta in tools.items():
            guard.register_actions(
                tool_id,
                description=str(meta.get("description") or ""),
                actions=dict(meta.get("actions") or {}),
            )
    except BOUNDARY_ERRORS as exc:  # 风险策略注册失败时宁可停用外部工具
        logger.warning("MCP 工具未接入风险策略，已跳过：%s", exc)
        raise


def _discover() -> tuple[dict[str, Any], dict[str, McpServerConfig]]:
    tools: dict[str, Any] = {}
    servers: dict[str, McpServerConfig] = {}
    for config in load_server_configs():
        try:
            infos = list_tools(config)
        except BOUNDARY_ERRORS as exc:  # 单个服务器异常不影响其他服务器
            logger.warning("MCP 服务器 %s 不可用：%s", config.name, exc)
            continue
        if not infos:
            continue
        tool_id = tool_id_for(config.name)
        actions = {info.name: _action_spec(info) for info in infos}
        for name in RESOURCE_ACTIONS:
            actions.setdefault(name, dict(_RESOURCE_ACTION_SPECS[name]))
        tools[tool_id] = {
            "description": f"外部 MCP 服务器 {config.name}（{len(actions)} 个工具）",
            "availability": "shared",
            "actions": actions,
        }
        servers[tool_id] = config
    if tools:
        _register_with_guard(tools)
    return tools, servers


def _snapshot(now: float | None = None) -> tuple[dict[str, Any], dict[str, McpServerConfig]]:
    current = time.time() if now is None else now
    with _CACHE_LOCK:
        if _CACHE["at"] and current - float(_CACHE["at"]) < _CACHE_TTL_SECONDS:
            return _CACHE["tools"], _CACHE["servers"]
        tools, servers = _discover()
        _CACHE.update(at=current, tools=tools, servers=servers)
        return tools, servers


def merge_mcp_tools(registry: dict[str, Any]) -> dict[str, Any]:
    """把已发现的外部工具并入工作流注册表；无配置时原样返回。"""
    if not mcp_enabled():
        return registry
    try:
        tools, _servers = _snapshot()
    except BOUNDARY_ERRORS as exc:
        logger.warning("MCP 工具发现失败，按无外部工具运行：%s", exc)
        with _CACHE_LOCK:
            _CACHE.update(at=time.time(), tools={}, servers={})
        return registry
    if not tools:
        return registry
    merged = dict(registry)
    for tool_id, meta in tools.items():
        merged.setdefault(tool_id, meta)
    return merged


def call_mcp_tool(
    tool_id: str, action: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """执行外部 MCP 工具；未发现或已过期时返回明确错误。"""
    try:
        _tools, servers = _snapshot()
    except BOUNDARY_ERRORS as exc:
        return {"success": False, "message": f"外部工具不可用：{exc}"}
    config = servers.get(str(tool_id))
    if config is None:
        return {"success": False, "message": f"外部工具未注册：{tool_id}"}
    arguments = {
        key: value for key, value in dict(params or {}).items() if not str(key).startswith("_")
    }
    return call_tool(config, str(action), arguments)


def reset_mcp_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE.update(at=0.0, tools={}, servers={})


__all__ = [
    "call_mcp_tool",
    "merge_mcp_tools",
    "reset_mcp_cache_for_tests",
    "tool_id_for",
]
