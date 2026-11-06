"""客服员工事件与客户定制交付状态机之间的隔离策略。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def is_delivery_managed(intent: str, evidence: dict[str, Any]) -> bool:
    return (
        intent == "custom_delivery"
        or str(evidence.get("delivery_managed_by") or "") == "custom_delivery"
    )


def success_reply(subject: str, progress: str, delivery_managed: bool) -> str:
    if delivery_managed:
        return (
            f"我是小C。工单「{subject}」值班员工已提交生产结果。"
            f"进展：{progress}。产物还需继续通过质量门、您的验收和桌面安装回执。"
        )
    return (
        f"我是小C。工单「{subject}」值班员工已提交处理结果。"
        f"进展：{progress}。还需确认正式发布和您的客户端运行验证，工单会继续跟进。"
    )


def apply_ticket_outcome(ticket: Any, team_ok: bool, delivery_managed: bool) -> None:
    """员工自动回写不能把未指派工单推进到处理中，也不能覆盖待客户确认。"""
    status = str(getattr(ticket, "status", "") or "")
    if status in {"awaiting_customer", "resolved", "closed", "expired"}:
        ticket.updated_at = datetime.now(UTC)
        return
    if status in {"", "open", "pending", "queued"}:
        ticket.closed_at = None
        ticket.updated_at = datetime.now(UTC)
        return
    if not delivery_managed:
        ticket.decision_status = "approved"
    ticket.status = "processing"
    ticket.closed_at = None
    ticket.updated_at = datetime.now(UTC)


__all__ = ["apply_ticket_outcome", "is_delivery_managed", "success_reply"]
