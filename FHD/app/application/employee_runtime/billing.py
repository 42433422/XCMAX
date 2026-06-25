"""员工运行时 LLM 计费桥。

把员工（tier-3 平台员工 / loops）的 LLM 调用接进统一钱包计费
（``record_model_usage`` → 按 token 估算 cost_units → 扣 AI 钱包）。此前员工 LLM
裸调 OpenAI 兼容客户端、完全不计费；这里补齐。

设计：``EmployeeAgent.run`` 在顶层用 :func:`begin_employee_billing` 把 user_id/run_id
存进 contextvar；两个 LLM 调用点（认知 ``_chat_completion`` 返回的 dict、agent_loop
的 OpenAI completion 对象）在**同线程同步**取回响应后调 :func:`bill_employee_llm_from_dict`
/ :func:`bill_employee_llm_from_completion`，从 contextvar 取 user_id 计费。

计费失败永不阻断执行（员工照常返回结果，只是这一笔没记上）。
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_BILLING_CTX: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "employee_billing_ctx", default=None
)


def begin_employee_billing(
    *, user_id: Any = 0, run_id: str = "", employee_id: str = ""
) -> contextvars.Token:
    """进入员工执行作用域，记录计费归属。返回 token 供 :func:`end_employee_billing` 复位。"""
    return _BILLING_CTX.set(
        {
            "user_id": str(user_id or ""),
            "run_id": str(run_id or ""),
            "employee_id": str(employee_id or ""),
        }
    )


def end_employee_billing(token: contextvars.Token) -> None:
    try:
        _BILLING_CTX.reset(token)
    except (ValueError, LookupError):  # token 跨上下文等异常，忽略
        pass


def _ctx() -> dict[str, str]:
    return _BILLING_CTX.get() or {}


def _extract_from_dict(raw: Any) -> tuple[int, int, int, str]:
    usage = raw.get("usage") if isinstance(raw, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    pt = _int(usage.get("prompt_tokens"))
    ct = _int(usage.get("completion_tokens"))
    tt = _int(usage.get("total_tokens"))
    model = str(raw.get("model") or "") if isinstance(raw, dict) else ""
    return pt, ct, tt, model


def _extract_from_completion(completion: Any) -> tuple[int, int, int, str]:
    usage = getattr(completion, "usage", None)
    pt = _int(getattr(usage, "prompt_tokens", 0))
    ct = _int(getattr(usage, "completion_tokens", 0))
    tt = _int(getattr(usage, "total_tokens", 0))
    model = str(getattr(completion, "model", "") or "")
    return pt, ct, tt, model


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _bill(pt: int, ct: int, tt: int, model: str, *, source: str) -> None:
    if tt <= 0 and pt <= 0 and ct <= 0:
        return  # 无 token 信息（多为出错响应），不计
    ctx = _ctx()
    try:
        from app.infrastructure.billing.model_usage import record_model_usage

        record_model_usage(
            run_id=ctx.get("run_id", ""),
            user_id=ctx.get("user_id", ""),
            provider="employee_runtime",
            model=model or "employee-llm",
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            source=source,
            usage_key=f"emp_{ctx.get('run_id', '')}_{uuid.uuid4().hex}",
            metadata={"employee_id": ctx.get("employee_id", ""), "kind": "employee_llm"},
        )
    except RECOVERABLE_ERRORS:
        logger.warning("员工 LLM 计费失败（不阻断执行）", exc_info=True)


def bill_employee_llm_from_dict(raw: Any, *, source: str = "employee_runtime") -> None:
    """从 adapter.chat_completion 返回的 dict（含 ``usage``）计费。"""
    pt, ct, tt, model = _extract_from_dict(raw)
    _bill(pt, ct, tt, model, source=source)


def bill_employee_llm_from_completion(completion: Any, *, source: str = "employee_runtime") -> None:
    """从 OpenAI completion 对象（含 ``.usage``）计费。"""
    pt, ct, tt, model = _extract_from_completion(completion)
    _bill(pt, ct, tt, model, source=source)


__all__ = [
    "begin_employee_billing",
    "end_employee_billing",
    "bill_employee_llm_from_dict",
    "bill_employee_llm_from_completion",
]
