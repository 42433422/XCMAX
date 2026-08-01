from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

_BUSINESS_MUTATION_VERB_RE = re.compile(
    r"删除|删掉|去掉|移除|注销|新增|添加|创建|录入|写入|入库|导入|"
    r"修改|更新|改成|改为|撤销|取消|提交|审批|批准",
    re.IGNORECASE,
)
_BUSINESS_ENTITY_RE = re.compile(
    r"客户|购买单位|买家|客商|产品|商品|物料|材料|库存|发货单|送货单|"
    r"订单|报价|价格|员工|人员|考勤|请假|数据库|ERP",
    re.IGNORECASE,
)
_MUTATION_COMPLETION_CLAIM_RE = re.compile(
    r"(?:已经|已|成功|完成).{0,10}(?:删除|删掉|去掉|移除|注销|新增|添加|创建|"
    r"录入|写入|入库|导入|修改|更新|撤销|取消|提交|批准)|"
    r"(?:删除|删掉|去掉|移除|注销|新增|添加|创建|录入|写入|入库|导入|"
    r"修改|更新|撤销|取消|提交|批准).{0,10}(?:成功|完成|了)",
    re.IGNORECASE,
)
_MUTATING_TOOL_ACTIONS = {
    "create", "ensure_exists", "upsert", "update", "delete", "batch_delete",
    "write", "import", "import_records", "import_delivery_notes", "submit",
    "approve", "cancel",
}


def _iter_payload_dicts(payload: dict[str, Any], max_depth: int = 3) -> Iterator[dict[str, Any]]:
    stack: list[tuple[dict[str, Any], int]] = [(payload, 0)]
    seen: set[int] = set()
    while stack:
        item, depth = stack.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        if depth >= max_depth:
            continue
        for key in ("data", "payload", "result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                stack.append((nested, depth + 1))


def _legacy_tool_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("legacy_tool_records", "_tool_records", "tool_records"):
            records = item.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
    return []


def _business_context_present(message: str, runtime_context: dict[str, Any] | None) -> bool:
    if _BUSINESS_ENTITY_RE.search(str(message or "")):
        return True
    recent = (runtime_context or {}).get("recent_messages") if runtime_context else None
    return isinstance(recent, list) and any(
        isinstance(item, dict) and _BUSINESS_ENTITY_RE.search(str(item.get("content") or ""))
        for item in recent[-6:]
    )


def _verified_mutation_evidence(payload: dict[str, Any]) -> bool:
    for item in _iter_payload_dicts(payload):
        receipt = item.get("execution_receipt") or item.get("business_receipt")
        if isinstance(receipt, dict) and receipt.get("executed") is True and receipt.get("verified") is True:
            return True
    for record in _legacy_tool_records(payload):
        action = str(record.get("action") or "").strip().lower()
        output = record.get("output")
        if action in _MUTATING_TOOL_ACTIONS and isinstance(output, dict) and output.get("success"):
            return True
    return False


def apply_business_mutation_evidence_gate(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    response_text = " ".join(str(value or "") for value in (
        payload.get("response"), payload.get("message"), data.get("text"),
    ))
    blocked = bool(
        payload.get("success") is not False
        and _BUSINESS_MUTATION_VERB_RE.search(str(message or ""))
        and _business_context_present(message, runtime_context)
        and _MUTATION_COMPLETION_CLAIM_RE.search(response_text)
        and not _verified_mutation_evidence(payload)
    )
    metadata["business_mutation_evidence_gate"] = "blocked" if blocked else "not_triggered"
    if not blocked:
        return False
    safe_text = (
        "业务变更未确认执行：没有检测到可验证的业务工具调用或写入回执。"
        "系统未把模型回复当成数据库变更结果，请从结构化任务卡重新执行。"
    )
    receipt = {
        "domain": "business_data", "operation": "mutation", "status": "unverified",
        "executed": False, "verified": False, "affected_rows": 0,
        "reason": "missing_verified_tool_receipt",
    }
    payload.update({
        "success": False, "message": safe_text, "response": safe_text,
        "error_code": "unverified_business_mutation", "execution_receipt": receipt,
    })
    if not data:
        data = {}
        payload["data"] = data
    data.update({
        "text": safe_text, "error_code": "unverified_business_mutation",
        "execution_receipt": receipt,
    })
    return True
