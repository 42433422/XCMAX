"""MCP 工具接入：把外部工具并入现有注册表与风险策略。

默认无配置文件即完全停用；发现结果缓存 5 分钟，避免每轮对话拉起子进程。
外部工具沿用现有权限、风险门、审批与租户边界，不新增旁路。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from app.domain.autonomy.browser_policy import (
    BROWSER_OBSERVATIONS,
    browser_action_allowed,
)
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
_CACHE: dict[str, Any] = {"at": 0.0, "tools": {}, "servers": {}, "config_digest": ""}

_SLUG = re.compile(r"[^A-Za-z0-9_]+")


def _slug(value: str) -> str:
    cleaned = _SLUG.sub("_", str(value or "").strip()).strip("_")
    return cleaned.lower() or "server"


def tool_id_for(server_name: str) -> str:
    return f"mcp__{_slug(server_name)}"


def _is_read_only(info: McpToolInfo, config: McpServerConfig) -> bool:
    # Names and remote annotations are untrusted capability claims, not authorization.
    return info.name in config.read_only_tools and info.read_only is True


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


def _action_spec(info: McpToolInfo, config: McpServerConfig) -> dict[str, Any]:
    read_only = _is_read_only(info, config) and (
        not config.browser or info.name in BROWSER_OBSERVATIONS
    )
    wire_schema = info.input_schema if isinstance(info.input_schema, dict) else {}
    schema = deepcopy(wire_schema)
    required = schema.get("required")
    required_params = (
        [str(item) for item in required if str(item).strip()] if isinstance(required, list) else []
    )
    description = info.description
    if config.browser and info.name not in BROWSER_OBSERVATIONS:
        from app.domain.autonomy.browser_evidence import BROWSER_POSTCONDITION_SCHEMA

        properties = schema.setdefault("properties", {})
        if "verification" in properties:
            raise ValueError("Browser wire schema collides with host verification field")
        properties["verification"] = deepcopy(BROWSER_POSTCONDITION_SCHEMA)
        required_params.append("verification")
        schema["required"] = list(required_params)
        description += (
            " 动作须附 verification 并经原审批。navigate 使用 kind=url 且 expected 等于请求 URL；"
            "其他写动作使用 kind=text，observation_call_id 引用同一父任务最新已核验 browser_snapshot。"
            "宿主写前回读确认文本尚不存在、ref仍有效，写后独立读取同一会话；仅证明可见页面状态。"
        )
    return {
        "risk": "low" if read_only else "high",
        "idempotent": read_only,
        "read_only": read_only,
        "input_schema": deepcopy(schema),
        "wire_input_schema": deepcopy(wire_schema),
        "required_params": required_params,
        "availability": "shared",
        "description": description,
        "timeout_seconds": config.timeout_seconds,
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
        try:
            from app.application.agent_orchestrator.tool_spec import invalidate_tool_specs_cache

            invalidate_tool_specs_cache()
        except (ImportError, OSError):
            pass
    except BOUNDARY_ERRORS as exc:  # 风险策略注册失败时宁可停用外部工具
        logger.warning("MCP 工具未接入风险策略，已跳过：%s", exc)
        raise


def _discover(
    configs: list[McpServerConfig],
) -> tuple[dict[str, Any], dict[str, McpServerConfig]]:
    tools: dict[str, Any] = {}
    servers: dict[str, McpServerConfig] = {}
    for config in configs:
        try:
            infos = list_tools(config)
        except BOUNDARY_ERRORS as exc:  # 单个服务器异常不影响其他服务器
            logger.warning("MCP 服务器 %s 不可用：%s", config.name, exc)
            continue
        if not infos:
            continue
        tool_id = tool_id_for(config.name)
        if tool_id in servers:
            raise ValueError(f"Ambiguous MCP server identity: {config.name}")
        actions = {info.name: _action_spec(info, config) for info in infos}
        for name in RESOURCE_ACTIONS:
            actions.setdefault(name, dict(_RESOURCE_ACTION_SPECS[name]))
        tools[tool_id] = {
            "description": (
                f"外部 MCP 服务器 {config.name}（{len(actions)} 个工具）"
                + (
                    "。Xiaox 按实际 browser_snapshot 发现 ref 并逐个提交明确动作；"
                    "同一受信父任务共享会话，每次写入独立审批和回读，不能猜测 ref 或重放未知结果。"
                    if config.browser and config.session_mode == "persistent"
                    else ""
                )
            ),
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
        configs = load_server_configs()
        digest = hashlib.sha256(
            json.dumps([asdict(config) for config in configs], sort_keys=True).encode()
        ).hexdigest()
        if (
            _CACHE["at"]
            and _CACHE["config_digest"] == digest
            and current - float(_CACHE["at"]) < _CACHE_TTL_SECONDS
        ):
            return _CACHE["tools"], _CACHE["servers"]
        tools, servers = _discover(configs)
        _CACHE.update(at=current, tools=tools, servers=servers, config_digest=digest)
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
    tool_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    *,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行外部 MCP 工具；未发现或已过期时返回明确错误。"""
    if not mcp_enabled():
        return {"success": False, "message": "外部 MCP 工具已停用"}
    try:
        tools, servers = _snapshot()
    except BOUNDARY_ERRORS as exc:
        return {"success": False, "message": f"外部工具不可用：{exc}"}
    config = servers.get(str(tool_id))
    if config is None or str(action) not in tools.get(str(tool_id), {}).get("actions", {}):
        return {"success": False, "message": f"外部工具或动作未注册：{tool_id}.{action}"}
    arguments = {
        key: value for key, value in dict(params or {}).items() if not str(key).startswith("_")
    }
    if config.browser:
        if not browser_action_allowed(str(action), arguments):
            return {
                "success": False,
                "error_code": "mcp_browser_action_rejected",
                "message": "浏览器动作或参数超出已启用的页面操作范围",
                "retryable": False,
            }
    spec = tools[str(tool_id)]["actions"][str(action)]
    from app.application.agent_orchestrator.tool_spec import validate_schema_object

    valid, message = validate_schema_object(spec.get("input_schema") or {}, arguments)
    if not valid:
        return {
            "success": False,
            "error_code": "mcp_arguments_invalid",
            "message": message,
            "retryable": False,
        }
    if config.browser and action not in BROWSER_OBSERVATIONS:
        try:
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash
            from app.application.agent_orchestrator.verification_surface import (
                execution_surface_binding,
            )
            from app.application.tools.surface_authority import require_surface_authority

            _actor, run = require_surface_authority(
                tool_id, action, arguments, runtime_context or {}, approval_required=True
            )
            binding = execution_surface_binding(run, arguments, runtime_context or {})
            call = next(
                (item for item in run.tool_calls if item.call_id == binding.get("call_id")), None
            )
            acceptance = (
                (call.metadata.get("verification_contract") or {}).get("surface_acceptance")
                if call
                else None
            )
            if (
                not isinstance(acceptance, dict)
                or acceptance.get("scope") != "live_page_assertion"
                or acceptance.get("config_sha256") != canonical_hash(asdict(config))
                or acceptance.get("session_scope") != mcp_session_scope(runtime_context or {})
            ):
                raise PermissionError("browser has no original frozen postcondition")
        except (ValueError, PermissionError):
            return {
                "success": False,
                "error_code": "mcp_browser_verification_required",
                "execution_status": "not_started",
                "retryable": False,
                "message": "浏览器动作缺少当前账号的原审批、页面观察或有效后置条件，未执行。",
            }
        arguments.pop("verification", None)
        valid, message = validate_schema_object(spec.get("wire_input_schema") or {}, arguments)
        if not valid:
            return {
                "success": False,
                "error_code": "mcp_arguments_invalid",
                "execution_status": "not_started",
                "message": message,
                "retryable": False,
            }
    options: dict[str, Any] = {"retry_safe": spec.get("idempotent") is True}
    if config.session_mode == "persistent":
        context = dict(runtime_context or {})
        scope = mcp_session_scope(context)
        if not scope:
            return {
                "success": False,
                "error_code": "mcp_session_scope_required",
                "message": "有状态工具需要服务端企业、用户与运行身份",
                "retryable": False,
            }
        options["session_scope"] = scope
        try:
            outputs = (
                browser_session_outputs(context, str(tool_id))
                if config.browser
                else list((context.get("node_outputs") or {}).values())
            )
        except (PermissionError, ValueError):
            return {
                "success": False,
                "error_code": "mcp_session_scope_required",
                "execution_status": "not_started",
                "retryable": False,
            }
        generations = {
            value["session_id"]
            for value in outputs
            if isinstance(value, dict)
            and value.get("server") == config.name
            and isinstance(value.get("session_id"), str)
            and value["session_id"]
        }
        if len(generations) > 1:
            return {
                "success": False,
                "error_code": "mcp_session_lost",
                "message": "原任务包含不一致的浏览器会话，需核对后重新开始",
                "retryable": False,
                "reconciliation_required": True,
            }
        if generations:
            options["expected_session_id"] = next(iter(generations))
    return call_tool(config, str(action), arguments, **options)


def mcp_session_scope(context: dict[str, Any]) -> str:
    """Only trusted executor context can bind a browser; model arguments cannot."""
    identity = [str(context.get(key) or "").strip() for key in ("tenant_id", "user_id", "run_id")]
    if context.get("source") == "xiaox_runtime" and context.get("parent_run_id"):
        from app.infrastructure.xiaox.receipts import action_parent

        try:
            parent = action_parent(context)
        except (ValueError, PermissionError):
            return ""
        if parent is None:
            return ""
        identity[2] = parent[1].run_id
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest() if all(identity) else ""


def browser_session_outputs(context: dict, tool_id: str) -> list[dict]:
    from app.infrastructure.xiaox.receipts import browser_action_receipts

    outputs = context.get("node_outputs")
    current = [
        value
        for value in (outputs.values() if isinstance(outputs, dict) else [])
        if isinstance(value, dict)
    ]
    return [row["record"].output for row in browser_action_receipts(context, tool_id)] + current


def browser_server_config(tool_id: str) -> McpServerConfig | None:
    """A remote tool name/annotation cannot opt itself into the browser runtime."""
    if not mcp_enabled():
        return None
    _tools, servers = _snapshot()
    config = servers.get(str(tool_id))
    return config if config and config.browser and config.session_mode == "persistent" else None


def release_run_browser_sessions(context: dict[str, Any]) -> int:
    from app.application.agent_orchestrator.browser_tool_process import close_browser_worker_scope
    from app.infrastructure.mcp.client import close_scope

    if context.get("source") == "xiaox_runtime" and context.get("parent_run_id"):
        # A dynamic child does not own the shared parent session lifetime.
        return 0

    scope = mcp_session_scope(context)
    if not scope:
        return 0
    return close_browser_worker_scope(scope) + close_scope(scope)


def reset_mcp_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE.update(at=0.0, tools={}, servers={}, config_digest="")


__all__ = [
    "call_mcp_tool",
    "merge_mcp_tools",
    "reset_mcp_cache_for_tests",
    "tool_id_for",
]
