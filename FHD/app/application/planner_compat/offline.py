"""Shared offline boundary for compatibility chat entry points."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from fastapi import Request

from .admission import ChatAdmission
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
) -> Payload:
    """Never invoke a model; execute only the existing protected local business handlers."""
    # Vector pre-indexing may use an online embedding provider.
    admitted = replace(admission, vector_guard=lambda _message, _context: None).check(request, turn)
    if admitted.payload is not None:
        return admitted.payload
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
        "response": "当前为离线模式。可使用已支持的本地业务功能；普通问答需要切换到在线模式。",
        "data": {
            "action": "offline_response",
            "mode": "offline",
            "model_called": False,
        },
    }
