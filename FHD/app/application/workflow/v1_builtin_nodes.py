"""纯转换与受控 HTTP 节点；不再承载嵌套工作流执行。

设计要点：
- 每个节点是独立函数，签名 (params, runtime_context) -> dict
- runtime_context 通过 params["_runtime_context"] 注入
- 模板变量：{{ var_name }} 在 url/headers/body/path 中替换
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

import httpx

from app.utils.operational_errors import RECOVERABLE_ERRORS


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
                    return cast("str", m.group(0))
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
            except RECOVERABLE_ERRORS:
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
            return cast("bool", actual == expected)
        if op == "neq":
            return cast("bool", actual != expected)
        if op == "gt":
            return cast("bool", actual > expected)
        if op == "lt":
            return cast("bool", actual < expected)
        if op == "gte":
            return cast("bool", actual >= expected)
        if op == "lte":
            return cast("bool", actual <= expected)
        if op == "contains":
            return expected in str(actual or "")
    except (TypeError, ValueError):
        return False
    return False
