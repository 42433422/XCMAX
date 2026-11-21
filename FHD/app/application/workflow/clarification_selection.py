"""Bound model-assisted clarification to the server-owned candidate set."""

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ConfigDict, StrictBool

from .clarification_lifecycle import option_letter_ordinal, resolve_confirmed_target

CONFIRM_WORDS = {"确认", "是", "是的", "好的", "好", "继续", "执行", "确认执行", "ok", "yes"}
CANCEL_WORDS = {"取消", "否", "不要", "停止", "no"}


def looks_like_continuation_reply(text: str) -> bool:
    """判断用户消息是否更像在回答上一轮提问，而不是新的业务目标。

    只覆盖确定性很强的短回复：单字母选项、一两位序号、确认类词。
    长句或新的业务目标返回 False，避免把新任务错误地接到旧问题上。
    """
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKC", str(text or "").strip()).rstrip("。.!！,，")
    if not normalized or len(normalized) > 24:
        return False
    lowered = normalized.lower()
    if lowered in CANCEL_WORDS:
        return False
    if lowered in CONFIRM_WORDS:
        return True
    if re.fullmatch(r"[A-Za-z]", normalized):
        return True
    return normalized.isdigit() and len(normalized) <= 2


def build_continuation_message(message: str, question: str) -> str:
    """把上一轮助手提问与用户本轮作答拼成一次可规划的续跑请求。"""
    return (
        f"{message}\n\n[承接上下文] 上一轮助手向用户提问：{question}\n"
        "请把本轮内容视作对该提问的回答，结合会话历史里的原始业务目标直接完成任务；"
        "信息已足够时不要再追问，也不要重复要求确认。"
    )

_PLAN_CONFIRM_PREFIXES = ("确认", "确定", "同意", "可以", "好的", "执行", "继续", "是", "对")
_PLAN_CANCEL_PREFIXES = ("取消", "不要", "不用", "别", "停止", "算了", "否")


def plan_confirmation_decision(text: str) -> bool | None:
    """解析计划级确认答复；返回 None 表示既不是确认也不是取消。"""
    normalized = str(text or "").strip().lower().rstrip("。.!！,，")
    if not normalized:
        return None
    if normalized in CANCEL_WORDS or normalized.startswith(_PLAN_CANCEL_PREFIXES):
        return False
    if normalized in CONFIRM_WORDS or all(
        part.strip() in _PLAN_CONFIRM_PREFIXES for part in normalized.replace("，", ",").split(",")
    ):
        return True
    return None


class ClarificationExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_kind: Literal["answer", "new_goal", "unclear"]
    resolved: StrictBool
    parameters: dict[str, Any]


CLARIFICATION_PARSER = PydanticOutputParser(pydantic_object=ClarificationExtraction)


def select_clarified_target(
    text: str,
    candidates: list[dict[str, Any]],
    *,
    affirmative: bool,
    extract: Callable[..., dict[str, Any] | None],
    request: dict[str, Any],
) -> dict[str, Any] | None:
    selected = resolve_confirmed_target(text, candidates)
    if selected is not None or not candidates:
        return selected
    duplicate_name = (
        sum(
            text.strip()
            in {
                str(item.get(key) or "").strip()
                for key in ("name", "customer_name", "unit_name", "product_name", "material_name")
            }
            for item in candidates
        )
        > 1
    )
    if affirmative or text.strip().isdigit() or option_letter_ordinal(text) or duplicate_name:
        return None
    selected = extract(**request, answer=text, allowed_fields={"id"}, candidates=candidates)
    if (
        not isinstance(selected, dict)
        or set(selected) != {"id"}
        or str(selected["id"]) not in {str(item.get("id")) for item in candidates}
    ):
        return None
    return selected
