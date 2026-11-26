"""Server-owned plan mode: a plan turn may describe work but never perform it."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

ExecutionMode = Literal["plan", "execute"]

CONTEXT_KEY = "_runtime_execution_mode"
METADATA_KEY = "runtime_execution_mode"
CONVERSATION_KEY = "execution_mode"


class ExecutionModeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_mode(value: Any, *, default: ExecutionMode = "execute") -> ExecutionMode:
    if value is None or value == "":
        return default
    if value == "plan":
        return "plan"
    if value == "execute":
        return "execute"
    raise ExecutionModeError("execution_mode_invalid", "执行模式无效")


def tighten(current: Any, requested: Any) -> ExecutionMode:
    """A caller may tighten to plan, never release a stored plan by requesting execute."""
    stored = normalize_mode(current)
    if requested is None:
        return stored
    wanted = normalize_mode(requested, default=stored)
    if stored == "plan" and wanted == "execute":
        raise ExecutionModeError("execution_mode_locked", "方案模式只能通过明确的执行操作解除")
    return wanted


_EXECUTE_PHRASES = (
    "执行方案",
    "按方案执行",
    "按计划执行",
    "开始执行",
    "直接执行",
    "立即执行",
    "照这个做",
    "就按这个来",
)
_PLAN_PHRASES = ("先不执行", "不要执行", "暂不执行", "怎么做", "如何做", "评估一下")
_PLAN_REQUEST = re.compile(
    r"(做|制定|起草|写|整理|列|出|给|设计|规划).{0,8}(方案|计划|草案|规划|思路)"
)
_NEGATED_EXECUTION = re.compile(
    r"(?:不要|别|不必|不准|禁止|暂不|先不|不想|不需要)[^，。！？；\n]{0,12}(?:执行|照这个做|就按这个来)"
)
_EXECUTE_REQUEST = re.compile(
    r"(?:(?:请(?:你)?|现在|那就|我确认)[，,\s]*)*(?:"
    + "|".join(_EXECUTE_PHRASES)
    + r")(?:吧)?[。！!\s]*"
)


def requested_mode_from_text(text: str) -> ExecutionMode | None:
    """Only an affirmative instruction may release plan mode; refusals stay locked."""
    body = str(text or "").strip()
    if (
        _NEGATED_EXECUTION.search(body)
        or _PLAN_REQUEST.search(body)
        or any(phrase in body for phrase in _PLAN_PHRASES)
    ):
        return "plan"
    # Additional clauses may restrict permission (for example, "wait for my
    # approval"). Only a complete affirmative command can release a saved plan.
    if _EXECUTE_REQUEST.fullmatch(body):
        return "execute"
    return None


def is_read_only_call(
    tool_id: str,
    action: str,
    params: dict[str, Any] | None,
    *,
    lookup_spec: Callable[[str, str], Any],
) -> bool:
    if (tool_id, action) == ("elt_import", "preview"):
        return True
    spec = lookup_spec(tool_id, action)
    if spec is None:
        return False
    checker = getattr(spec, "is_read_only_call", None)
    if params is not None and callable(checker):
        try:
            return bool(checker(params))
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
    return bool(spec.read_only)


def deny_reason(
    mode: Any,
    tool_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    *,
    lookup_spec: Callable[[str, str], Any],
) -> str:
    """Return a refusal for plan mode; unknown tools stay blocked, not trusted."""
    if normalize_mode(mode) != "plan":
        return ""
    if is_read_only_call(str(tool_id or ""), str(action or ""), params, lookup_spec=lookup_spec):
        return ""
    return "当前会话处于方案模式，尚未获得执行授权，本轮不得执行业务写入、审批或子任务。"
