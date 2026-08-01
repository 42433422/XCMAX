"""客服员工事件与客户定制交付状态机之间的隔离策略。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def is_delivery_managed(intent: str, evidence: dict[str, Any]) -> bool:
    return intent == "custom_delivery" or str(evidence.get("delivery_managed_by") or "") == "custom_delivery"


def success_reply(subject: str, progress: str, delivery_managed: bool) -> str:
    if delivery_managed:
        return (
            f"我是小C。工单「{subject}」值班员工已提交生产结果。"
            f"进展：{progress}。产物还需继续通过质量门、您的验收和桌面安装回执。"
        )
    return (
        f"我是小C。工单「{subject}」值班员工已完成排查修复并验证通过。"
        f"进展：{progress}。如仍复现请再补充截图。"
    )


def apply_ticket_outcome(ticket: Any, team_ok: bool, delivery_managed: bool) -> None:
    """定制交付不能被员工事件提前结案；普通客服工单维持原行为。"""
    if not delivery_managed:
        ticket.decision_status = "approved"
    ticket.status = "resolved" if team_ok and not delivery_managed else "processing"
    ticket.closed_at = datetime.now(timezone.utc) if ticket.status == "resolved" else None
    ticket.updated_at = datetime.now(timezone.utc)


__all__ = ["apply_ticket_outcome", "is_delivery_managed", "success_reply"]
