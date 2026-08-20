# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def prepare_business_db_write_target(
    entity: str, operation: str, payload: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """Resolve update/delete targets without mutating business data.

    The result is shared by the clarification gate and the final dispatcher, so approval previews
    and execution use the same exact, tenant-scoped target.
    """
    normalized = dict(payload or {})
    if operation not in {"update", "delete"}:
        return {"success": True, "payload": normalized}
    if bool(normalized.get("force")):
        return {
            "success": False,
            "reason": "force_not_allowed",
            "message": "智能对话不允许 force 删除；请先处理关联数据。",
        }
    selector = _facade()._business_db_selector(normalized)
    candidates, selector_field = _facade()._business_db_target_candidates(entity, selector)
    if not selector_field:
        return {
            "success": False,
            "reason": "missing_target",
            "message": "更新或删除必须提供当前租户内的唯一 ID 或受支持的精确自然键。",
            "candidates": [],
        }
    if not candidates:
        return {
            "success": False,
            "reason": "target_not_found",
            "message": "当前租户内未找到目标记录，未执行写入。",
            "candidates": [],
        }
    if len(candidates) > 1:
        return {
            "success": False,
            "reason": "ambiguous_target",
            "message": "精确条件匹配到多条记录，请选择唯一 ID。",
            "candidates": candidates,
        }
    target = candidates[0]
    normalized["id"] = int(target["id"])
    normalized["_selector_field"] = selector_field
    normalized["_resolved_target"] = target
    return {"success": True, "payload": normalized, "target": target}


def _remember_business_db_target(
    runtime_context: dict[str, _facade().Any],
    entity: str,
    operation: str,
    payload: dict[str, _facade().Any],
    result: dict[str, _facade().Any],
) -> dict[str, _facade().Any]:
    if not result.get("success") or operation == "delete":
        return result
    target_id = _facade()._result_record_id(result) or _facade()._result_record_id(payload)
    if not target_id and operation in {"create", "ensure_exists", "upsert"}:
        candidates, _ = _facade()._business_db_target_candidates(
            entity, _facade()._business_db_selector(payload)
        )
        if len(candidates) == 1:
            target_id = int(candidates[0]["id"])
    user_id = str(runtime_context.get("user_id") or "").strip()
    if user_id and target_id:
        _facade()._RECENT_BUSINESS_DB_TARGETS[user_id] = {"entity": entity, "id": int(target_id)}
    return result
