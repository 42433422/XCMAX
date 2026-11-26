"""Shared offline boundary for compatibility chat entry points."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from .admission import AdmissionResult, ChatAdmission
from .protocols import ChatTurn, Payload


def is_offline(mode: str | None) -> bool:
    explicit = str(mode or "").strip().lower()
    if explicit in {"online", "offline"}:
        return explicit == "offline"
    from app.infrastructure.llm.client import resolve_mode

    return resolve_mode() == "offline"


def offline_turn(
    request: Request,
    turn: ChatTurn,
    admission: ChatAdmission,
    business: Callable[..., Payload | None],
    *,
    admitted: AdmissionResult | None = None,
) -> Payload:
    """Allow only explicitly classified local reads; never fall back to a legacy writer."""
    admitted = admitted if admitted is not None else admission.check(request, turn)
    if admitted.payload is not None:
        return admitted.payload

    from app.domain.app_pure.chat_business_safety import classify_business_chat_intent

    intent = classify_business_chat_intent(turn.message)
    if intent is None:
        return offline_unavailable_payload()
    if intent.operation not in {"personnel_read", "attendance_read"}:
        message = "离线聊天不再直接执行业务写入、导出或打印。请切换在线模式，或使用对应业务模块。"
        return {
            "success": False,
            "response": message,
            "message": message,
            "execution_state": "not_started",
            "error_code": "runtime_offline_mutation_blocked",
            "data": {
                "action": "offline_response",
                "mode": "offline",
                "model_called": False,
                "operation": intent.operation,
                "error_code": "runtime_offline_mutation_blocked",
            },
        }
    result = business(
        turn.message,
        runtime_context=turn.context,
        user_id=turn.body.user_id,
        request=request,
    )
    if result is not None:
        return result
    return offline_unavailable_payload()


def offline_unavailable_payload() -> Payload:
    return {
        "success": False,
        "response": "当前为离线模式。可使用已授权的本地只读查询；其他聊天任务需要切换到在线模式。",
        "data": {
            "action": "offline_response",
            "mode": "offline",
            "model_called": False,
        },
    }
