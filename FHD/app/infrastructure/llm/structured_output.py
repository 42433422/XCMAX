"""Structured Output：JSON 提取 → schema 校验 → 带错误反馈的修复重试。

- schema 校验复用 tool_spec 的轻量实现（零新增生产依赖）。
- LLM 调用经 invoke 统一入口（自动获得遥测 + guardrails）。
- 终败抛 ``StructuredOutputError``，由调用方决定降级策略。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, cast

from app.infrastructure.llm import invoke
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_REPAIR_TEMPLATE = (
    "你上次返回的内容未通过 JSON Schema 校验。\n"
    "校验错误：{errors}\n"
    "原始输出：{raw}\n"
    "请只返回修正后的 JSON，不要解释、不要 markdown 代码块。"
)


class StructuredOutputError(Exception):
    """修复重试耗尽后抛出。"""

    def __init__(self, attempts: int, last_errors: list[str], last_raw: str) -> None:
        super().__init__(f"structured output failed after {attempts} attempts: {last_errors}")
        self.attempts = attempts
        self.last_errors = last_errors
        self.last_raw = last_raw


@dataclass
class StructuredResult:
    data: dict[str, Any]
    attempts: int
    repaired: bool
    trace_id: str | None = None
    billing: dict[str, Any] | None = None
    model: str = ""


def extract_json(content: str) -> dict[str, Any] | None:
    """从 LLM 输出提取 object 根 JSON；容忍 fence 与首尾废话。"""
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def validate_payload(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    """复用 tool_spec 轻量 schema 校验。"""
    from app.application.agent_orchestrator.tool_spec import _validate_schema_payload

    return _validate_schema_payload(schema, payload, subject="LLM 输出")


def _max_repairs_default() -> int:
    raw = (os.environ.get("XCAGI_STRUCTURED_OUTPUT_MAX_REPAIRS") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


async def complete_structured(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_repairs: int | None = None,
    profile: str = "default",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    conversation_service: Any | None = None,
) -> StructuredResult:
    """调用 LLM 并保证返回通过 schema 校验的 dict；失败带反馈重试。"""
    repairs = _max_repairs_default() if max_repairs is None else max(0, max_repairs)
    total_attempts = 1 + repairs
    attempt_messages = list(messages)
    last_errors: list[str] = ["尚未调用"]
    last_raw = ""

    for attempt in range(1, total_attempts + 1):
        try:
            result = await invoke.chat_completion_openai_format(
                attempt_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                profile=profile,
                conversation_service=conversation_service,
            )
        except RECOVERABLE_ERRORS as exc:
            last_errors = [f"LLM 调用异常: {type(exc).__name__}: {exc}"]
            logger.warning("complete_structured attempt %s failed: %s", attempt, exc)
            continue
        if result is None:
            last_errors = ["LLM 调用失败或被 guardrail 拦截"]
            continue
        choices = result.get("choices") or []
        raw = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
        last_raw = raw
        data = extract_json(raw)
        if data is None:
            last_errors = ["输出中未找到有效 JSON object"]
        else:
            ok, message = validate_payload(schema, data)
            if ok:
                billing: dict[str, Any] = {}
                try:
                    from app.infrastructure.llm.platform_billing_pass import (
                        billing_meta_from_response,
                    )

                    billing = billing_meta_from_response(result)
                except RECOVERABLE_ERRORS:
                    billing = {}
                return StructuredResult(
                    data=data,
                    attempts=attempt,
                    repaired=attempt > 1,
                    trace_id=_current_trace_id(),
                    billing=billing or None,
                    model=str(result.get("model") or billing.get("resolved_model") or ""),
                )
            last_errors = [message]
        attempt_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": _REPAIR_TEMPLATE.format(errors="；".join(last_errors), raw=raw[:2000]),
            },
        ]

    raise StructuredOutputError(total_attempts, last_errors, last_raw)


def _current_trace_id() -> str | None:
    try:
        from app.neuro_bus.tracer import current_trace

        return current_trace.get()
    except Exception:  # noqa: BLE001
        return None


def complete_structured_sync(
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float = 120.0,
    **kwargs: Any,
) -> StructuredResult:
    """同步上下文桥：无运行 loop 直接 asyncio.run；有 loop 则独立线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(complete_structured(messages, **kwargs))

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(complete_structured(messages, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise StructuredOutputError(0, ["sync bridge timeout"], "")
    return cast(StructuredResult, box["result"])
