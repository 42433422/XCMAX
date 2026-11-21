"""Bound model-assisted clarification to the server-owned candidate set."""

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ConfigDict, StrictBool

from .clarification_lifecycle import option_letter_ordinal, resolve_confirmed_target

CONFIRM_WORDS = {"确认", "是", "是的", "好的", "好", "继续", "执行", "确认执行", "ok", "yes"}
CANCEL_WORDS = {"取消", "否", "不要", "停止", "no"}


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
