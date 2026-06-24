"""执行/LLM 失败分类：区分「配额/计费/额度耗尽」与「可能由 prompt 导致」的失败。

为什么需要它：自进化引擎仅按 ``status != "success"`` 选取要重写 prompt 的员工，
但「配额不足/欠费/403」类失败改 prompt 无法修复 —— 继续重写只会再发一次 LLM 调用，
把上游 403 放大成「死亡螺旋」（生产实测 99.6% 失败、有用产出≈0）。

``EmployeeExecutionMetric.failure_kind`` 写入本模块的分类，进化引擎据此排除配额类失败。
"""

from __future__ import annotations

import re
from typing import Optional

# 失败大类（写入 EmployeeExecutionMetric.failure_kind）
FAILURE_KIND_QUOTA = "quota"  # 配额/额度/计费/欠费/402/403 —— 改 prompt 无效，必须排除出重写候选
FAILURE_KIND_TRANSIENT = "transient"  # 限流/超时/网关抖动 —— 重试可恢复，亦非 prompt 问题
FAILURE_KIND_PROMPT = "prompt"  # 其它（可能由 prompt/逻辑导致，进化引擎可据此重写）
FAILURE_KIND_NONE = ""  # 无错误

# 命中即判定为配额/计费类（小写子串匹配）。覆盖中英文上游与内部配额闸门。
_QUOTA_NEEDLES = (
    "配额",  # 配额不足 / 缺少配额（quota_middleware.require_llm_credit 抛 403:配额不足:llm_calls）
    "额度",  # 额度不足
    "余额不足",
    "欠费",
    "quota",
    "insufficient_quota",
    "insufficient quota",
    "insufficient balance",
    "insufficient_balance",
    "insufficient credit",
    "insufficient funds",
    "credit balance",
    "out of credit",
    "billing",
    "payment required",
    "llm_calls",
    "arrearage",
    "exceeded your current quota",
)

# HTTP 状态码 → 配额/计费（402 Payment Required / 403 Forbidden 多由额度/计费闸门返回）
_QUOTA_STATUS = {402, 403}

# 命中即判定为瞬时（与 employee_executor._is_transient_llm_error 同源，重试可恢复）
_TRANSIENT_NEEDLES = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "rate limit",
    "ratelimit",
    "429",
    "503",
    "502",
    "504",
    "bad gateway",
    "service unavailable",
    "eof occurred",
    "broken pipe",
    "connection refused",
    "connecterror",
    "readtimeout",
    "remotedisconnected",
    "try again",
    "overloaded",
)

_TRANSIENT_STATUS = {429, 502, 503, 504}

# FastAPI/Starlette ``str(HTTPException(403, "..."))`` 形如 ``"403: 配额不足: llm_calls"``。
_LEADING_STATUS_RE = re.compile(r"^\s*(\d{3})\b")


def _leading_status_code(text: str) -> Optional[int]:
    """从 ``"403: 配额不足"`` 这类 HTTPException 字符串中提取前导状态码。"""
    m = _LEADING_STATUS_RE.match(text or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:  # pragma: no cover - 正则已保证三位数字
        return None


def is_quota_or_billing_failure(error_text: str, status_code: Optional[int] = None) -> bool:
    """该失败是否由配额/额度/计费/欠费导致（改 prompt 无法修复）。"""
    text = error_text or ""
    code = status_code if status_code is not None else _leading_status_code(text)
    if code in _QUOTA_STATUS:
        return True
    low = text.lower()
    return any(n in low for n in _QUOTA_NEEDLES)


def is_transient_failure(error_text: str, status_code: Optional[int] = None) -> bool:
    """该失败是否为瞬时网络/限流抖动（重试可恢复）。"""
    text = error_text or ""
    code = status_code if status_code is not None else _leading_status_code(text)
    if code in _TRANSIENT_STATUS:
        return True
    low = text.lower()
    return any(n in low for n in _TRANSIENT_NEEDLES)


def classify_failure_kind(error_text: str, status_code: Optional[int] = None) -> str:
    """把一段错误信息映射到失败大类。

    优先级：配额/计费 > 瞬时 > prompt。配额优先于瞬时是刻意的：部分上游（如 OpenAI
    ``insufficient_quota``）把额度耗尽放在 HTTP 429 下返回，本质仍是「改 prompt 无效」，
    不能被当成可重试的限流，更不能触发自进化重写。
    """
    text = (error_text or "").strip()
    if not text:
        return FAILURE_KIND_NONE
    if is_quota_or_billing_failure(text, status_code):
        return FAILURE_KIND_QUOTA
    if is_transient_failure(text, status_code):
        return FAILURE_KIND_TRANSIENT
    return FAILURE_KIND_PROMPT


__all__ = [
    "FAILURE_KIND_QUOTA",
    "FAILURE_KIND_TRANSIENT",
    "FAILURE_KIND_PROMPT",
    "FAILURE_KIND_NONE",
    "classify_failure_kind",
    "is_quota_or_billing_failure",
    "is_transient_failure",
]
