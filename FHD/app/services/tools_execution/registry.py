from __future__ import annotations

CANONICAL_ACTIONS = {
    "view",
    "list",
    "query",
    "create",
    "update",
    "delete",
    "batch_delete",
    "import",
    "export",
    "analyze",
    "extract",
    "preview",
    "execute",
    "read",
    "write",
}

ACTION_ALIASES = {
    "查找": "query",
    "查询": "query",
    "搜索": "query",
    "search": "query",
    "find": "query",
    "add": "create",
    "新增": "create",
    "添加": "create",
    "create": "create",
    "modify": "update",
    "edit": "update",
    "更新": "update",
    "删除": "delete",
    "remove": "delete",
    "del": "delete",
    "删除批量": "batch_delete",
    "batch-delete": "batch_delete",
    "batch_delete": "batch_delete",
    "导入": "import",
    "导出": "export",
    "分析": "analyze",
    "提取": "extract",
    "执行": "execute",
    "exec": "execute",
    "run": "execute",
    "读取": "read",
    "读": "read",
    "read": "read",
    "写入": "write",
    "写": "write",
    "write": "write",
}


def _normalize_action(action: str, params: dict | None = None) -> str:
    raw = str(action or "").strip()
    if not raw:
        return "view"
    lowered = raw.lower()
    normalized = ACTION_ALIASES.get(raw) or ACTION_ALIASES.get(lowered) or lowered
    if normalized in CANONICAL_ACTIONS:
        return normalized
    if params and str(params.get("action") or "").strip():
        nested = str(params.get("action")).strip()
        nested_lower = nested.lower()
        mapped = ACTION_ALIASES.get(nested) or ACTION_ALIASES.get(nested_lower) or nested_lower
        if mapped in CANONICAL_ACTIONS:
            return mapped
    return normalized


def _validate_required_params(tool_id: str, action: str, params: dict | None) -> tuple[bool, str]:
    from app.application.shipment_inputs import missing_shipment_call_fields

    missing = missing_shipment_call_fields(tool_id, action, dict(params or {}))
    if missing:
        return False, "缺少有效出货参数：" + "、".join(missing)
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    spec = get_tool_action_spec(tool_id, action)
    required = spec.required_params if spec is not None else []
    if not required:
        return True, ""
    payload = dict(params or {})
    missing = [
        key
        for key in required
        if payload.get(key) is None
        or isinstance(payload.get(key), str)
        and not payload[key].strip()
        or isinstance(payload.get(key), list)
        and not payload[key]
    ]
    if missing:
        return False, f"缺少参数：{', '.join(missing)}"
    return True, ""


def get_workflow_tool_registry(
    runtime_context: dict | None = None, *, include_aiopen: bool = False
) -> dict:
    """Project the execution contracts; context-bearing discovery is account scoped."""
    from app.application.capability_catalog import workflow_registry

    return workflow_registry(runtime_context, include_aiopen=include_aiopen)
