"""Value objects and token estimation for LLM billing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Union

from modstore_server.multimodal_llm import VISION_IMAGE_TOKEN_ESTIMATE


@dataclass
class UsageMeter:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


@dataclass
class WalletHold:
    hold_no: str
    amount: Decimal
    enabled: bool


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_str(value: Decimal | float | int | str) -> str:
    return format(money(value), "f")


def estimate_tokens_from_text(text: str) -> int:
    return max(1, int(len(text or "") / 4) + 1)


def estimate_tokens_from_message_content(content: Union[str, list, Any]) -> int:
    if isinstance(content, str):
        return estimate_tokens_from_text(content)
    if isinstance(content, list):
        count = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                count += estimate_tokens_from_text(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                count += VISION_IMAGE_TOKEN_ESTIMATE
        return max(1, count)
    return 1


def usage_from_response(
    raw_usage: Dict[str, Any] | None,
    messages: Iterable[Dict[str, Any]],
    content: str,
) -> UsageMeter:
    usage = raw_usage or {}
    prompt = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokenCount")
        or 0
    )
    completion = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("candidatesTokenCount")
        or 0
    )
    total = int(usage.get("total_tokens") or usage.get("totalTokenCount") or 0)
    if prompt or completion or total:
        return UsageMeter(prompt, completion, total or prompt + completion, estimated=False)
    prompt = sum(estimate_tokens_from_message_content(row.get("content")) for row in messages)
    completion = estimate_tokens_from_text(content)
    return UsageMeter(prompt, completion, prompt + completion, estimated=True)
