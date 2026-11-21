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
from typing import TYPE_CHECKING, Any

from app.domain.autonomy.browser_policy import (
    BROWSER_ACTIONS,
    MAX_BROWSER_DECISIONS,
    MAX_BROWSER_SECONDS,
    MAX_BROWSER_STEPS,
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

if TYPE_CHECKING:
    from app.application.workflow.workflow_types import PlanGraph

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
    read_only = _is_read_only(info, config)
    schema = info.input_schema if isinstance(info.input_schema, dict) else {}
    required = schema.get("required")
    required_params = (
        [str(item) for item in required if str(item).strip()] if isinstance(required, list) else []
    )
    return {
        "risk": "low" if read_only else "high",
        "idempotent": read_only,
        "read_only": read_only,
        "input_schema": deepcopy(schema),
        "required_params": required_params,
        "availability": "shared",
        "description": info.description,
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
                    "。AI 浏览器任务：仅规划一个 browser_navigate 或 browser_snapshot 起始节点，"
                    "不得预先猜测页面 ref 或混入其他工具。原目标由同一 AgentRun 按最新页面逐步操作，"
                    "每次动作使用现有权限审批，最终必须回读验证；请在原用户任务中明确完成条件。"
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
        outputs = context.get("node_outputs")
        generations = {
            value["session_id"]
            for value in (outputs.values() if isinstance(outputs, dict) else [])
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
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest() if all(identity) else ""


def browser_server_config(tool_id: str) -> McpServerConfig | None:
    """A remote tool name/annotation cannot opt itself into the browser runtime."""
    if not mcp_enabled():
        return None
    _tools, servers = _snapshot()
    config = servers.get(str(tool_id))
    return config if config and config.browser and config.session_mode == "persistent" else None


def browser_execution_contract(plan: PlanGraph) -> dict[str, Any] | None:
    """Describe only a local, valid controller entry; plan claims never enable it."""
    if len(plan.nodes) != 1:
        return None
    seed = plan.nodes[0]
    if (
        not seed.tool_id.startswith("mcp__")
        or seed.action not in {"browser_navigate", "browser_snapshot"}
        or seed.depends_on
        or seed.next
        or seed.branches
        or not browser_action_allowed(seed.action, seed.params)
    ):
        return None
    if browser_server_config(seed.tool_id) is None:
        return None
    return {
        "seed_node_id": seed.node_id,
        "tool_id": seed.tool_id,
        "actions": sorted(BROWSER_ACTIONS),
        "limits": {
            "steps": MAX_BROWSER_STEPS,
            "model_decisions": MAX_BROWSER_DECISIONS,
            "scheduling_deadline_seconds": MAX_BROWSER_SECONDS,
        },
        "semantics": (
            "这个本地认可的单节点是原 AgentRun 的浏览器控制入口，不是任务完成声明。"
            "执行层每次读取实际页面，再向同一图追加一个动作，重新经过原权限、审批和预算。"
            "用户授权的同一连续浏览器交互可作为一个控制目标映射到该入口；"
            "该目标仍必须完整保留原话中的对象、范围、否定、条件和先后顺序。"
        ),
        "verification_scope": (
            "终态仅证明 browser_wait_for 对非空文本成功，随后同会话新快照读回该文本；"
            "不能证明未读回的业务数据库、付款或外部投递成功。"
        ),
        "handoff": "登录、验证码、外部发送、付款和不支持的操作须暂停询问，不能宣称完成。",
        "review_requirement": (
            "必须独立判断整个原始目标是否能由这些动作及页面文本验证覆盖。"
            "不能遗漏不属于该连续浏览器交互的其他目标，不能因为存在控制入口就判通过；"
            "若目标超出能力，沿用原 violations/unsupported/clarification_question 规则。"
        ),
    }


def release_run_browser_sessions(context: dict[str, Any]) -> int:
    from app.application.agent_orchestrator.browser_tool_process import close_browser_worker_scope
    from app.infrastructure.mcp.client import close_scope

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
