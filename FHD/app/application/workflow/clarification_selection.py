"""Bound model-assisted clarification to the server-owned candidate set."""

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

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

    @model_validator(mode="after")
    def coherent_answer(self) -> "ClarificationExtraction":
        if self.turn_kind != "answer" and (self.resolved or self.parameters):
            raise ValueError("Only an answer may resolve a clarification")
        if not self.resolved and self.parameters:
            raise ValueError("An unresolved answer cannot supply parameters")
        return self


class ClarificationTurnError(ValueError):
    """A failed classification is different from a valid, unclear user turn."""

    def __init__(self, *, unavailable: bool = False, failure: dict[str, Any] | None = None) -> None:
        self.failure = failure or {}
        self.code = "model_response_invalid"
        self.retryable = True
        super().__init__("澄清识别服务未返回有效结果" if unavailable else "澄清识别结果不符合协议")


CLARIFICATION_PARSER = PydanticOutputParser(pydantic_object=ClarificationExtraction)


def select_clarified_target(
    text: str,
    candidates: list[dict[str, Any]],
    *,
    affirmative: bool,
    extract: Callable[..., ClarificationExtraction],
    request: dict[str, Any],
) -> dict[str, Any] | ClarificationExtraction | None:
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
    turn = extract(**request, answer=text, allowed_fields={"id"}, candidates=candidates)
    if turn.turn_kind != "answer":
        return turn
    selected = turn.parameters if turn.resolved else None
    if (
        not isinstance(selected, dict)
        or set(selected) != {"id"}
        or str(selected["id"]) not in {str(item.get("id")) for item in candidates}
    ):
        return None
    return selected
