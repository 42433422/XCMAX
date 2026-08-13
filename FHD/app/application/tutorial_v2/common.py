"""Shared constants and safe serialization helpers for Tutorial V2."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

SALES_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"
ACTIVE_RUN_STATUSES = {"active", "paused"}
SAFE_HINTS = {
    "prerequisite_incomplete": "请先完成前置课程。",
    "previous_step_incomplete": "请先验证通过上一必修步骤。",
    "tutorial_context_required": "请点击“进入教学空间”后再验证。",
    "customer_not_ready": "请确认教学空间中只有一条名称精确为“客户B”的客户。",
    "product_not_ready": "请确认“A 产品”的价格为 100、库存为 100，且只有一条。",
    "task_not_completed": "请先完成一项只读查询任务。",
    "task_evidence_not_ready": "请打开已完成任务的结果证据后重试。",
    "second_task_not_ready": "请用自己的说法完成产品列表查询，并查看第二项任务的结果证据。",
    "approval_not_ready": "请按精确句子提交并确认任务，且暂不要批准。",
    "approval_detail_not_viewed": "请打开真实待审批详情，核对客户、产品、数量和金额后再验证。",
    "sales_result_not_ready": "请批准申请后检查订单、库存、开票、收款和凭证。",
    "etl_preview_not_ready": "请先完成上传、字段映射和预览核对。",
    "etl_result_not_ready": "请确认写入并查看逐行导入结果。",
    "trace_view_required": "请先点击“去操作”打开当前步骤要求的页面。",
    "trace_result_not_ready": "当前页面对应的业务证据尚未完整。",
    "verification_passed": "验证通过，下一步已解锁。",
}


def utcnow() -> datetime:
    return datetime.utcnow()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


class TutorialServiceError(RuntimeError):
    def __init__(self, code: str, hint: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.hint = hint
        self.status_code = status_code
