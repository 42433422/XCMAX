"""工作流新节点（V1 扩展）：http_request / data_transform / loop / sub_workflow。

设计要点：
- 每个节点是独立函数，签名 (params, runtime_context) -> dict
- 与现有 WorkflowEngine._dispatch 接口兼容（runtime_context 通过 params["_runtime_context"] 注入）
- 模板变量：{{ var_name }} 在 url/headers/body/path 中替换
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.utils.operational_errors import OPERATIONAL_ERRORS

from .types import PlanGraph, WorkflowNode

logger = logging.getLogger(__name__)


# ---------------------- 模板变量替换 ----------------------

_VAR_PATTERN = re.compile(r"\{\{\s*([\w\.\-]+)\s*\}\}")


def _resolve_template(value: Any, ctx: dict[str, Any]) -> Any:
    """把 {{ var }} 替换为 ctx[var]（支持 dict/list 递归）。"""
    if isinstance(value, str):

        def repl(m: re.Match) -> str:
            path = m.group(1)
            cur: Any = ctx
            for part in path.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return m.group(0)
            return str(cur)

        return _VAR_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_template(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template(v, ctx) for v in value]
    return value


def _runtime_ctx(params: dict[str, Any]) -> dict[str, Any]:
    return params.get("_runtime_context") or {}


# ---------------------- http_request ----------------------


def execute_http_request_node(
    params: dict[str, Any], runtime_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    HTTP 请求节点。

    params:
      method: GET/POST/PUT/DELETE (default GET)
      url: 完整 URL（含 https://）
      headers: dict (optional)
      body: any (optional) — 自动 JSON 序列化
      timeout: seconds (default 30)
      retries: int (default 0)
    """
    method = str(params.get("method") or "GET").upper()
    url = str(params.get("url") or "").strip()
    if not url:
        return {"success": False, "error_code": "missing_url", "message": "缺少 url"}
    if not url.lower().startswith(("http://", "https://")):
        return {
            "success": False,
            "error_code": "invalid_url",
            "message": "url 必须以 http(s):// 开头",
        }
    # 安全：默认只允许 https；可配置白名单
    allow_http_hosts = {"localhost", "127.0.0.1"}
    if url.lower().startswith("http://"):
        host = url.split("/")[2] if "//" in url else ""
        if host.split(":")[0] not in allow_http_hosts:
            return {
                "success": False,
                "error_code": "http_not_allowed",
                "message": "非 HTTPS 需白名单",
            }

    ctx = runtime_context or _runtime_ctx(params)
    method = _resolve_template(method, ctx)
    url = _resolve_template(url, ctx)
    headers = _resolve_template(params.get("headers") or {}, ctx)
    body = _resolve_template(params.get("body"), ctx)
    timeout = float(params.get("timeout") or 30)
    retries = int(params.get("retries") or 0)

    last_err: str = ""
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.request(
                    method=method, url=url, headers=headers, json=body if body is not None else None
                )
            try:
                data = resp.json()
            except OPERATIONAL_ERRORS:
                data = {"raw": resp.text}
            return {
                "success": resp.status_code < 400,
                "status_code": resp.status_code,
                "method": method,
                "url": url,
                "data": data,
                "message": f"HTTP {method} {resp.status_code}",
            }
        except (httpx.HTTPError, ValueError, TypeError) as e:
            last_err = str(e)
            logger.warning("http_request attempt %d failed: %s", attempt, last_err)
    return {"success": False, "error_code": "http_failed", "message": last_err}


# ---------------------- data_transform ----------------------


def execute_data_transform_node(
    params: dict[str, Any], runtime_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    数据转换节点。

    params:
      input: 任意可解析对象（dict / list）
      mappings: list of {from: "$.path", to: "new.path", default: any}
      filter: 可选 — list 时按 condition 过滤
      condition: dict {op: "gt|lt|eq|contains", field: "$.x", value: ...}
    """
    ctx = runtime_context or _runtime_ctx(params)
    input_data = params.get("input")
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except (ValueError, TypeError):
            pass
    if input_data is None:
        # 允许从 ctx 注入
        input_data = ctx.get("transform_input")

    if input_data is None:
        return {"success": False, "error_code": "missing_input", "message": "缺少 input"}

    mappings = params.get("mappings") or []
    out: dict[str, Any] = {}

    for m in mappings:
        if not isinstance(m, dict):
            continue
        from_path = str(m.get("from") or "").lstrip("$.")
        to_path = str(m.get("to") or "").lstrip("$.")
        default = m.get("default")

        value = _get_by_path(input_data, from_path)
        if value is None and default is not None:
            value = default
        if value is not None:
            _set_by_path(out, to_path, value)

    # 可选过滤
    result_data: Any = out if mappings else input_data
    if isinstance(input_data, list) and params.get("condition"):
        cond = params["condition"]
        op = cond.get("op", "eq")
        field = str(cond.get("field") or "").lstrip("$.")
        target = cond.get("value")
        result_data = [
            item for item in input_data if _eval_condition(_get_by_path(item, field), op, target)
        ]

    return {
        "success": True,
        "data": result_data,
        "message": f"data_transform 完成：{len(mappings)} 个字段映射",
    }


def _get_by_path(obj: Any, path: str) -> Any:
    if not path:
        return obj
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        else:
            return None
    return cur


def _set_by_path(obj: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = obj
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _eval_condition(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op == "gt":
            return actual > expected
        if op == "lt":
            return actual < expected
        if op == "gte":
            return actual >= expected
        if op == "lte":
            return actual <= expected
        if op == "contains":
            return expected in str(actual or "")
    except (TypeError, ValueError):
        return False
    return False


# ---------------------- loop ----------------------

MAX_LOOP_ITER = 100


def execute_loop_node(
    params: dict[str, Any], runtime_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    循环节点（for_each / while）。

    params:
      mode: "for_each" | "while"
      items: list — for_each 的迭代源
      condition: dict — while 条件 {op, field, value}
      max_iter: int (default 100)
      body_plan: PlanGraph — 子图（V1 简化：仅支持一节点子图）
    """
    mode = str(params.get("mode") or "for_each").lower()
    max_iter = min(int(params.get("max_iter") or MAX_LOOP_ITER), MAX_LOOP_ITER)
    body_plan = params.get("body_plan")
    if body_plan is None:
        return {"success": False, "error_code": "missing_body_plan", "message": "缺少 body_plan"}

    ctx = dict(runtime_context or _runtime_ctx(params))
    results: list[dict[str, Any]] = []

    if mode == "for_each":
        items = params.get("items") or ctx.get("loop_items") or []
        if not isinstance(items, list):
            return {"success": False, "error_code": "invalid_items", "message": "items 必须为 list"}
        for idx, item in enumerate(items[:max_iter]):
            loop_ctx = {**ctx, "loop_item": item, "loop_index": idx}
            out = _execute_body_plan(body_plan, loop_ctx)
            results.append(out)
            if out.get("break_loop"):
                break
        return {
            "success": True,
            "iterations": len(results),
            "results": results,
            "message": f"loop for_each 完成 {len(results)} 次",
        }

    if mode == "while":
        cond = params.get("condition") or {}
        op = cond.get("op", "lt")
        field = str(cond.get("field") or "counter").lstrip("$.")
        target = cond.get("value", 0)
        counter = 0
        while counter < max_iter:
            loop_ctx = {**ctx, "loop_index": counter, "counter": counter}
            actual = _get_by_path(loop_ctx, field)
            if not _eval_condition(actual, op, target):
                break
            out = _execute_body_plan(body_plan, loop_ctx)
            results.append(out)
            if out.get("break_loop"):
                break
            counter += 1
        return {
            "success": True,
            "iterations": counter,
            "results": results,
            "message": f"loop while 完成 {counter} 次",
        }

    return {"success": False, "error_code": "invalid_mode", "message": f"未知 mode: {mode}"}


def _execute_body_plan(plan: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    """执行 body_plan（V1 简化：单节点 PlanGraph）。"""
    if not isinstance(plan, dict) and not isinstance(plan, PlanGraph):
        return {"success": False, "error_code": "invalid_body_plan", "message": "body_plan 非法"}
    nodes = getattr(plan, "nodes", None) or plan.get("nodes", [])
    if not nodes:
        return {"success": False, "error_code": "empty_body_plan", "message": "body_plan 无节点"}
    first = nodes[0]
    return _dispatch_builtin(first, ctx)


def _dispatch_builtin(node: WorkflowNode | dict, ctx: dict[str, Any]) -> dict[str, Any]:
    """内置节点 dispatch（http / data_transform / 子工作流 等）。"""
    if isinstance(node, dict):
        node.get("node_id", "n?")
        tool = node.get("tool_id")
        node.get("action")
        params = node.get("params") or {}
    else:
        tool = node.tool_id
        params = node.params or {}

    params = dict(params)
    params["_runtime_context"] = ctx

    # 尝试在 v1_builtin 节点表中 dispatch
    if tool in _V1_BUILTIN_NODES:
        try:
            return _V1_BUILTIN_NODES[tool](params, ctx)
        except (ValueError, TypeError, KeyError) as e:
            return {"success": False, "error_code": "builtin_error", "message": str(e)}

    return {
        "success": False,
        "error_code": "unsupported_builtin",
        "message": f"内置节点未实现: {tool}",
    }


# ---------------------- sub_workflow ----------------------


def execute_sub_workflow_node(
    params: dict[str, Any], runtime_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    子工作流节点。

    params:
      workflow_id: 父工作流 id（V1 简化：传 inline 子图）
      inline_plan: dict 形式的 PlanGraph（开发期便利）
      input_map: dict {子图 var: 父 ctx var}
      max_depth: int (default 3)
    """
    from .engine import WorkflowEngine

    inline_plan = params.get("inline_plan")
    if inline_plan is None:
        return {
            "success": False,
            "error_code": "missing_inline_plan",
            "message": "V1 简化版仅支持 inline_plan",
        }

    ctx = dict(runtime_context or _runtime_ctx(params))
    depth = int(ctx.get("sub_workflow_depth", 0))
    if depth >= int(params.get("max_depth", 3)):
        return {
            "success": False,
            "error_code": "max_depth",
            "message": f"子工作流递归深度 {depth} 超限",
        }

    # 把 inline_plan 转 PlanGraph
    if not isinstance(inline_plan, PlanGraph):
        return {
            "success": False,
            "error_code": "invalid_plan",
            "message": "inline_plan 须为 PlanGraph",
        }

    # 注入子 ctx
    inline_plan.metadata = {**(inline_plan.metadata or {}), "parent_ctx": ctx}
    sub_ctx = {**ctx, "sub_workflow_depth": depth + 1}

    # dispatch 仍走父 dispatcher（无 registry 时由 v1_builtin 兜底）
    parent_dispatcher = ctx.get("_dispatch")
    if parent_dispatcher is None:
        return {
            "success": False,
            "error_code": "missing_dispatcher",
            "message": "父 dispatcher 不可用",
        }

    engine = WorkflowEngine(tool_dispatcher=parent_dispatcher)
    return engine.run(plan=inline_plan, runtime_context=sub_ctx, agentic_loop=False).__dict__


# ---------------------- 节点注册表 ----------------------

_V1_BUILTIN_NODES = {
    "http_request": execute_http_request_node,
    "data_transform": execute_data_transform_node,
    "loop": execute_loop_node,
    "sub_workflow": execute_sub_workflow_node,
}


def get_v1_builtin_node_types() -> list[str]:
    return list(_V1_BUILTIN_NODES.keys())
