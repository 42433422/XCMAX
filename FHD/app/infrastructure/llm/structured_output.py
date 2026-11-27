"""Structured Output：JSON 提取 → schema 校验 → 带错误反馈的修复重试。

- schema 校验复用已锁定的 jsonschema，禁止类型强制转换和远程引用。
- LLM 调用经 invoke 统一入口（自动获得遥测 + guardrails）。
- 终败抛 ``StructuredOutputError``，由调用方决定降级策略。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from openai import APIError
from referencing import Registry

from app.application.tool_execution_deadline import (
    check_invocation_deadline,
    invocation_deadline,
    remaining_invocation_seconds,
)
from app.infrastructure.llm import invoke
from app.infrastructure.llm.response_completion import normal_finish_reason
from app.infrastructure.llm.retry_policy import is_safe_transport_retry, retry_delay
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_PROVIDER_ERRORS: tuple[type[Exception], ...] = (APIError,) + RECOVERABLE_ERRORS
_MAX_REPAIRS = 2

_REPAIR_TEMPLATE = (
    "你上次返回的内容未通过 JSON Schema 校验。\n"
    "校验错误：{errors}\n"
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
    if in_string or escape or not 0 < depth <= 2:
        return None
    try:
        parsed = json.loads(text[start:] + ("}" * depth))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_payload(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate the complete declared schema without rewriting model output."""
    validator = validator_for(schema)
    validator.check_schema(schema)
    try:
        validator(schema, registry=Registry()).validate(payload)
    except ValidationError as exc:
        return False, f"LLM 输出不符合 JSON Schema：{exc.message[:1000]}"
    return True, ""


def _max_repairs_default() -> int:
    raw = (os.environ.get("XCAGI_STRUCTURED_OUTPUT_MAX_REPAIRS") or "").strip()
    try:
        return min(_MAX_REPAIRS, max(0, int(raw)))
    except ValueError:
        return _MAX_REPAIRS


async def _complete_structured(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_repairs: int | None = None,
    profile: str = "default",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    conversation_service: Any | None = None,
    provider: Any | None = None,
) -> StructuredResult:
    """调用 LLM 并保证返回通过 schema 校验的 dict；失败带反馈重试。"""
    validator_for(schema).check_schema(schema)  # Configuration errors must fail before paid I/O.
    repairs = (
        _max_repairs_default() if max_repairs is None else min(_MAX_REPAIRS, max(0, max_repairs))
    )
    total_attempts = 1 + repairs
    # Only a definite rejection or pre-dispatch connection failure can retry.
    # Response loss, admission denial and guardrail blocks are not JSON errors.
    transport_retries_left = 2
    attempt_messages = list(messages)
    last_errors: list[str] = ["尚未调用"]
    last_raw = ""
    routing: dict[str, Any] = {}
    if conversation_service is not None:
        routing["conversation_service"] = conversation_service
    if provider is not None:
        routing["provider"] = provider

    attempts_used = 0
    while attempts_used < total_attempts:
        attempts_used += 1
        try:
            result = await invoke.chat_completion_openai_format(
                attempt_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                profile=profile,
                **routing,
            )
        except _PROVIDER_ERRORS as exc:
            if transport_retries_left <= 0 or not (
                is_safe_transport_retry(exc) or _is_rate_limited(exc)
            ):
                # Preserve admission, cancellation and uncertain usage outcomes.
                raise
            transport_retries_left -= 1
            headers = getattr(getattr(exc, "response", None), "headers", {})
            delay = retry_delay(2 - transport_retries_left, headers.get("retry-after"))
            logger.warning("complete_structured %s, retry in %.1fs", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            attempts_used -= 1  # Transport retries share one budget across every repair.
            continue
        if result is None:
            raise StructuredOutputError(attempts_used, ["LLM 调用失败或被 guardrail 拦截"], "")
        choices = result.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        if not isinstance(first, dict):
            first = {}
        message = first.get("message")
        if isinstance(message, dict) and message.get("refusal"):
            raise StructuredOutputError(attempts_used, ["模型明确拒绝本次请求"], "")
        if "finish_reason" in first and not normal_finish_reason(first["finish_reason"]):
            raise StructuredOutputError(
                attempts_used, ["模型响应未正常完成，禁止将局部 JSON 认定为成功"], ""
            )
        raw = message_text({"choices": [first]})
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
                    attempts=attempts_used,
                    repaired=attempts_used > 1,
                    trace_id=_current_trace_id(),
                    billing=billing or None,
                    model=str(result.get("model") or billing.get("resolved_model") or ""),
                )
            last_errors = [message]
        attempt_messages = [
            *messages,
            {"role": "assistant", "content": raw[:2000]},
            {
                "role": "user",
                "content": _REPAIR_TEMPLATE.format(errors="；".join(last_errors)),
            },
        ]

    raise StructuredOutputError(attempts_used, last_errors, last_raw)


def _is_rate_limited(exc: BaseException) -> bool:
    """Only structured provider status can authorize replay, never error text."""
    return getattr(getattr(exc, "response", None), "status_code", None) == 429


def _current_trace_id() -> str | None:
    try:
        from app.neuro_bus.tracer import current_trace

        return current_trace.get()
    except RECOVERABLE_ERRORS:
        return None


async def complete_structured(
    messages: list[dict[str, str]], *, timeout_seconds: float = 120.0, **kwargs: Any
) -> StructuredResult:
    """Bound every completion, retry and repair; cancellation reaches the provider."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("structured completion timeout must be positive and finite")
    timeout_seconds = remaining_invocation_seconds(timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    timer = asyncio.timeout(timeout_seconds)
    try:
        with invocation_deadline(deadline):
            check_invocation_deadline()
            async with timer:
                result = await _complete_structured(messages, **kwargs)
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if time.monotonic() >= deadline:
            raise TimeoutError
        return result
    except TimeoutError as exc:
        if not timer.expired() and time.monotonic() < deadline:
            raise  # A provider timeout is an uncertain request, not invalid JSON.
        raise StructuredOutputError(0, ["structured completion timeout"], "") from exc


async def complete_structured_bounded(
    messages: list[dict[str, str]], *, timeout_seconds: float = 120.0, **kwargs: Any
) -> StructuredResult:
    """Compatibility entry; the direct completion API now shares the same bound."""
    return await complete_structured(messages, timeout_seconds=timeout_seconds, **kwargs)


def complete_structured_sync(
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float = 120.0,
    **kwargs: Any,
) -> StructuredResult:
    """Compatibility for sync callers; async routes must await the bounded API."""

    def run() -> StructuredResult:
        return asyncio.run(
            complete_structured_bounded(messages, timeout_seconds=timeout_seconds, **kwargs)
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()

    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = run()
        except BOUNDARY_ERRORS as exc:
            box["error"] = exc

    # Legacy callers retain their synchronous contract, but their coroutine now
    # has its own deadline/cancellation and keeps tenant/request context.
    thread = threading.Thread(target=contextvars.copy_context().run, args=(runner,), daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise StructuredOutputError(0, ["sync bridge timeout"], "")
    return cast(StructuredResult, box["result"])


def message_text(response: dict[str, Any] | None) -> str:
    """Extract assistant text from an OpenAI-compatible completion payload."""
    choices = (response or {}).get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type", "text") == "text"
        ]
        return "".join(parts).strip()
    return str(content or "").strip()


async def complete_text(
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float = 60.0,
    **kwargs: Any,
) -> str:
    """Plain-text completion through the shared invoke entry (no schema repair)."""
    response = await asyncio.wait_for(
        invoke.chat_completion_openai_format(messages, **kwargs),
        timeout=timeout_seconds,
    )
    return message_text(response)


def complete_text_sync(
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float = 60.0,
    **kwargs: Any,
) -> str:
    """Sync bridge for worker-thread callers (FastAPI sync endpoints / tools)."""

    def run() -> str:
        return asyncio.run(complete_text(messages, timeout_seconds=timeout_seconds, **kwargs))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()

    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = run()
        except BOUNDARY_ERRORS as exc:
            box["error"] = exc

    thread = threading.Thread(target=contextvars.copy_context().run, args=(runner,), daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds + 5)
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise TimeoutError("sync completion timeout")
    return cast(str, box["result"])
