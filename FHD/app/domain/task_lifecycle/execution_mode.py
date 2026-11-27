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
_EXECUTE_ACTION = re.compile("|".join(map(re.escape, _EXECUTE_PHRASES)))
_EXECUTE_PREFIX = re.compile(
    r"(?:\s|请|你|帮我|替我|为我|现在|本轮|本次|这次|那就|就|可以|然后|接着|再|明确|"
    r"(?:我(?:已经|已|现在|明确)*\s*)?(?:确认|同意|批准|授权))*"
)
_EXECUTION_HOLD = re.compile(
    r"(?:不(?:要|必|得|能|许|应|可|允许)?|别|勿|无需|禁止|暂停|暂缓|停止)"
    r"\s*(?:再|马上|立即|直接|按.{0,8}方案)?\s*(?:执行|运行|操作)"
    r"|(?:撤回|撤销|收回|取消).{0,12}(?:执行|授权|批准)"
)
_QUOTED_TEXT = re.compile(
    r'“[^”]*(?:”|$)|‘[^’]*(?:’|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|"[^"]*(?:"|$)'
    r"|```[\s\S]*?(?:```|$)|`[^`]*(?:`|$)"
)
_MODE_TRANSITION = re.compile(r"但是|不过|但|然后|并(?:且)?(?=请|立即|直接|开始|按方案|执行方案)")
_MODE_CLAUSE = re.compile(r"[^，。；！？,;!?\n]+[！？?]?")
_WAIT_FOR_AUTHORIZATION = re.compile(r"(?:等待?|待).{0,10}(?:确认|同意|授权|批准|审批)")
_CURRENT_AUTHORIZATION = re.compile(r"现在|本轮|本次|这次|确认|同意|授权|批准")
_DEFERRED_SUFFIX = (
    "前",
    "之前",
    "方案前",
    "方案之前",
    "的话",
    "时",
    "还是",
    "或者",
    "怎么",
    "如何",
)


def requests_plan_document(text: str) -> bool:
    return bool(_PLAN_REQUEST.search(_QUOTED_TEXT.sub(" ", text)))


def requested_mode_from_text(text: str) -> ExecutionMode | None:
    """Only an unambiguous, current directive can release plan mode."""
    body = str(text or "")
    mode: ExecutionMode | None = (
        "plan"
        if any(_EXECUTE_ACTION.search(quote) for quote in _QUOTED_TEXT.findall(body))
        else None
    )
    unquoted = _MODE_TRANSITION.sub("，", _QUOTED_TEXT.sub(" ", body))
    waiting = False
    for part in _MODE_CLAUSE.findall(unquoted):
        clause = part.strip()
        if clause.startswith(("如果", "若", "除非")) or _WAIT_FOR_AUTHORIZATION.search(clause):
            mode, waiting = "plan", True
            continue
        action = _EXECUTE_ACTION.search(clause)
        if _EXECUTION_HOLD.search(clause):
            mode = "plan"
        elif action:
            prefix = clause[: action.start()]
            suffix = clause[action.end() :].lstrip()
            imperative = (
                _EXECUTE_PREFIX.fullmatch(prefix)
                and not clause.endswith(("?", "？", "吗", "么"))
                and not suffix.startswith(_DEFERRED_SUFFIX)
            )
            # A later directive may override a real wait only if it explicitly authorizes action now.
            if imperative and (not waiting or _CURRENT_AUTHORIZATION.search(prefix)):
                mode, waiting = "execute", False
            else:
                mode = "plan"
        elif _PLAN_REQUEST.search(clause) or any(phrase in clause for phrase in _PLAN_PHRASES):
            if mode is None or clause.lstrip("请 ").startswith(("只", "仅")):
                mode = "plan"
    return mode


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
