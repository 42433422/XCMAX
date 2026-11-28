"""Run-bound Responses forwarding through existing admission and billing.

This proxy does not translate Chat Completions or invent provider responses.
Only an explicitly qualified gateway is used; redirects, environment proxies,
native remote tools and client-supplied provider changes are rejected.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import sys
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import AsyncExitStack, ExitStack, aclosing, contextmanager
from types import SimpleNamespace
from typing import Any, get_args

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from httpx_sse import EventSource
from sqlalchemy.exc import DBAPIError
from starlette.types import Receive, Scope, Send

from app.application.agent_runtime.verification_budget import (
    JOB_HEADER,
    JOB_KEY,
    active_verification_job_id,
    phase_deadline,
    verification_reserve,
)
from app.infrastructure.billing.model_reservation import PlatformModelReceiptScope
from app.infrastructure.llm.retry_policy import retry_after_seconds, retry_delay
from app.infrastructure.xiaox.policy import ModelRoute

router = APIRouter()
logger = logging.getLogger(__name__)
MODEL_PATH = "/api/agent-runtime/xiaox/responses"
_ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def model_request_timeout_seconds(route: ModelRoute | None = None) -> float:
    """Upstream wait budget for one model request; the turn deadline still clamps it."""
    ceiling = route.request_timeout_seconds if route else 180.0
    raw = os.environ.get("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", str(ceiling)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = 180.0
    if not math.isfinite(value):
        value = 180.0
    return max(15.0 if route else 30.0, min(value, ceiling if route else 600.0))


def model_phase_timeout_seconds(phase: str, budget: float | None = None) -> float:
    """Separate transport/header/inference guards under the same request clock."""
    default = {"connect": 15.0, "pool": 15.0, "write": 15.0, "cleanup": 2.0}.get(
        phase, budget if budget is not None else model_request_timeout_seconds()
    )
    raw = os.environ.get(f"XCAGI_MODEL_{phase.upper()}_TIMEOUT_SEC", str(default))
    try:
        value = float(raw)
    except ValueError:
        value = default
    return max(0.1, min(value, 600.0)) if math.isfinite(value) and value > 0 else default


class ModelRequestTimeout(TimeoutError):
    """One model request exhausted its single absolute wait budget."""


def model_request_deadline(binding: Any, route: ModelRoute | None = None) -> float:
    """Start the one monotonic clock shared by headers, JSON and SSE settlement.

    The upstream phase timeout remains a transport guard, but it must never
    extend the request's absolute budget. Retries, header waits and body reads
    all consume the same clock, so a slow attempt cannot buy a fresh window.
    """
    return time.monotonic() + min(model_request_timeout_seconds(route), _remaining(binding))


def request_remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise ModelRequestTimeout("Model request budget expired")
    return left


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    return retry_after_seconds(headers.get("retry-after"))


async def _wait_for_model_retry(request: Request, delay: float) -> bool:
    import anyio

    with anyio.move_on_after(delay):
        while (await request.receive())["type"] != "http.disconnect":
            pass
        return False
    return True


_TERMINAL_STATES = frozenset({"completed", "incomplete", "failed"})
# 0.171 registers these local helper functions even when no business permission
# was granted to them. Keep the model's catalog limited to the bound MCP bridge.
# Unknown functions still fail admission; this list is tied to the pinned CLI.
_LOCAL_HELPERS = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "read_mcp_resource",
        "request_user_input",
        "view_image",
        "get_goal",
        "create_goal",
        "update_goal",
    }
)


class ModelGatewayContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _ModelOutputItemError(ValueError):
    def __init__(self, reason: str, **fields: str | None) -> None:
        super().__init__("Model output item did not match the controlled response contract")
        self.diagnostic = {"reason": reason, **fields}


def response_usage(response: dict[str, Any]) -> dict[str, int] | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt, output = usage.get("input_tokens"), usage.get("output_tokens")
    if type(prompt) is not int or type(output) is not int or prompt < 0 or output < 0:
        return None
    total = usage.get("total_tokens", prompt + output)
    if type(total) is not int or total < prompt + output:
        return None
    return {"prompt_tokens": prompt, "completion_tokens": output, "total_tokens": total}


def _validate_tools(tools: Any) -> None:
    from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

    if not isinstance(tools, list):
        raise HTTPException(400, "Invalid model tool list")
    for tool in tools:
        if not isinstance(tool, dict):
            raise HTTPException(400, "Invalid model tool")
        name = tool.get("name", "")
        # Xiaox can group MCP functions in a namespace. Only our bridge is valid.
        if tool.get("type") == "namespace" and name == "mcp__xcmax":
            children = tool.get("tools")
            if not isinstance(children, list) or any(
                not isinstance(item, dict) for item in children
            ):
                raise HTTPException(400, "Invalid model tool namespace")
            _validate_tools(
                [{**item, "name": f"mcp__xcmax__{item.get('name', '')}"} for item in children]
            )
        elif tool.get("type") != "function" or name not in {
            f"mcp__xcmax__{item}" for item in XIAOX_TOOL_NAMES
        }:
            raise HTTPException(403, "Only the controlled XCMAX MCP tools are allowed")


def _controlled_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        raise HTTPException(400, "Invalid model tool list")
    controlled = [
        tool
        for tool in tools
        if not (
            isinstance(tool, dict)
            and tool.get("type") == "function"
            and tool.get("name") in _LOCAL_HELPERS
        )
    ]
    _validate_tools(controlled)
    return controlled


def _validate_output_item(item: Any) -> None:
    from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

    if not isinstance(item, dict):
        raise _ModelOutputItemError("item_not_object")
    kind = item.get("type")
    if not isinstance(kind, str):
        raise _ModelOutputItemError("item_type_not_string")
    if kind in {"message", "reasoning", "compaction"}:
        return
    if kind != "function_call":
        from openai.types.responses import ResponseOutputItem

        # Report only the SDK's public discriminator values, never arbitrary provider text.
        item_models = get_args(get_args(ResponseOutputItem)[0])
        known_type = any(
            kind in get_args(model.model_fields["type"].annotation) for model in item_models
        )
        raise _ModelOutputItemError(
            "item_type_not_allowed", item_type=kind if known_type else "unrecognized"
        )
    name, namespace = item.get("name"), item.get("namespace")
    flat_names = {f"mcp__xcmax__{tool}" for tool in XIAOX_TOOL_NAMES}
    if isinstance(name, str) and (
        (namespace == "mcp__xcmax" and name in XIAOX_TOOL_NAMES)
        or (namespace in (None, "") and name in flat_names)
    ):
        return
    raise _ModelOutputItemError(
        "function_identity_not_allowed",
        item_type=kind,
        namespace=namespace if namespace in (None, "", "mcp__xcmax") else "unrecognized",
        name=name
        if isinstance(name, str) and name in flat_names.union(XIAOX_TOOL_NAMES, _LOCAL_HELPERS)
        else "unrecognized",
    )


def _validate_model_output(response: Any) -> None:
    if not isinstance(response, dict) or not isinstance(response.get("output", []), list):
        raise ValueError("Invalid model response")
    for item in response.get("output", []):
        _validate_output_item(item)


def _prepare_body(body: Any, route: ModelRoute) -> dict[str, Any]:
    from openai.types.responses.response_create_params import ResponseCreateParamsBase

    if not isinstance(body, dict) or body.get("model", route.model) != route.model:
        raise HTTPException(409, "The model route is pinned to this task")
    body = dict(body)
    # Pinned CLI 0.171 sends its own trace metadata; it is not a Responses
    # provider option or an authorization source. Keep it out of upstream I/O.
    body.pop("client_metadata", None)
    # Reuse the installed SDK's Responses field contract. Provider-specific
    # routing/fallback/retry controls belong to the qualified host, not the CLI.
    if body.keys() - ResponseCreateParamsBase.__annotations__.keys() - {"stream"}:
        raise HTTPException(400, "Unsupported Responses fields or provider routing controls")
    if body.get("background") or body.get("conversation") or body.get("previous_response_id"):
        raise HTTPException(400, "Remote conversation storage is not enabled")
    text = body.get("text")
    output_format = text.get("format") if isinstance(text, dict) else None
    if (
        route.upstream_vendor.strip().casefold() == "xiaomi"
        and route.model.startswith("mimo-")
        and isinstance(output_format, dict)
        and output_format.get("type") == "json_schema"
    ):
        schema = output_format.get("schema")
        instructions = body.get("instructions") or ""
        if (
            not isinstance(schema, dict)
            or schema.get("type") != "object"
            or not isinstance(instructions, str)
        ):
            raise HTTPException(400, "MiMo structured output requires an object schema")
        # MiMo Responses supports JSON objects. Preserve the requested schema in
        # its instructions; the host still validates proposals before dispatch.
        body["text"] = {**text, "format": {"type": "json_object"}}
        body["instructions"] = (
            instructions
            + "\n\nReturn only a JSON object conforming to this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
    tools = _controlled_tools(body.get("tools", []))
    maximum = body.get("max_output_tokens", route.max_output_tokens)
    if type(maximum) is not int or not 0 < maximum <= route.max_output_tokens:
        raise HTTPException(400, "Requested output exceeds the qualified model capacity")
    return {
        **body,
        "model": route.model,
        "max_output_tokens": maximum,
        "store": False,
        "tools": tools,
        # Existing MODstore LiteLLM wire contract; these are not generic
        # Responses fields and must never be sent to another gateway kind.
        **(
            {"num_retries": 0, "disable_fallbacks": True} if route.gateway_kind == "litellm" else {}
        ),
    }


def _portable_fallback_body(body: dict[str, Any]) -> bool:
    """Only self-contained Responses history may cross a qualified model route.

    Provider-side IDs and encrypted reasoning cannot be translated or dropped.
    Tool result strings stay unchanged; their business data is not a route grant.
    """
    if any(body.get(key) for key in ("prompt", "conversation", "previous_response_id")):
        return False
    history = body.get("input", [])
    if isinstance(history, list):
        calls = {
            item.get("call_id")
            for item in history
            if isinstance(item, dict)
            and item.get("type") == "function_call"
            and isinstance(item.get("call_id"), str)
        }
        if any(
            isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and (not isinstance(item.get("call_id"), str) or item["call_id"] not in calls)
            for item in history
        ):
            return False

    def portable(value: Any) -> bool:
        if isinstance(value, list):
            return all(portable(item) for item in value)
        if not isinstance(value, dict):
            return isinstance(value, (str, int, float, bool)) or value is None
        if any(
            value.get(key)
            for key in (
                "encrypted_content",
                "encrypted_function_args",
                "file_id",
                "container_id",
                "approval_request_id",
            )
        ):
            return False
        kind = value.get("type")
        if kind not in {
            None,
            "message",
            "input_text",
            "output_text",
            "function_call",
            "function_call_output",
            "refusal",
        }:
            return False
        if kind is None and (
            value.get("role") not in {"system", "developer", "user", "assistant"}
            or "content" not in value
        ):
            return False  # Includes the SDK's type-optional remote item reference.
        return all(portable(child) for child in value.values())

    return portable(history)


class _ModelCallLimitReached(Exception):
    """Raised inside a binding mutation so the refusal can be committed first."""

    def __init__(
        self,
        max_model_calls: int,
        used_model_calls: int,
        reason: str = "model_call_budget_exhausted",
    ) -> None:
        super().__init__("model call limit reached")
        self.max_model_calls = max_model_calls
        self.used_model_calls = used_model_calls
        self.reason = reason


def _remaining(binding: Any) -> float:
    value = phase_deadline(binding.run, binding.metadata)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise HTTPException(409, "Task model deadline is missing")
    remaining = float(value) - time.time()
    if remaining <= 0:
        raise HTTPException(408, "Task model deadline is exhausted")
    return remaining


def _claim(
    store: Any,
    token: str,
    route: ModelRoute,
    request_id: str,
    *,
    request_group: str = "",
    attempt: int = 1,
    expected_route_identity: str | None = None,
    observation: dict[str, Any] | None = None,
    verification_job: str = "",
) -> tuple[Any, int]:
    from app.application.agent_orchestrator.budget import budget_exceeded_payload
    from app.application.agent_orchestrator.task_context import ensure_run_trace
    from app.infrastructure.billing.model_usage import estimate_llm_cost_units
    from app.infrastructure.llm.model_admission import admit_model_call

    reserve = estimate_llm_cost_units(total_tokens=route.effective_context_window)
    with store.scope(token, audience="model") as binding:
        _remaining(binding)
        config = binding.metadata.get("runtime_config") or {}
        authorized = config.get("authorized_model_routes", [config.get("route_identity")])
        if (
            not isinstance(authorized, list)
            or route.identity not in authorized
            or (
                route.identity == config.get("route_identity")
                and config.get("model") != route.model
            )
        ):
            raise HTTPException(409, "The configured gateway no longer matches this task")
        admit_model_call(None, profile="xiaox", kwargs={"model": route.model})

        def claim(run: Any, metadata: dict[str, Any]) -> None:
            if (
                expected_route_identity is not None
                and run.metadata.get("runtime_effective_model_route", config.get("route_identity"))
                != expected_route_identity
            ):
                raise HTTPException(409, "The task's effective model changed during this request")
            expected_job = active_verification_job_id(run, metadata)
            if (verification_job or metadata.get("active_phase") == "verification") and (
                not verification_job or verification_job != expected_job
            ):
                raise HTTPException(403, "Model request is not bound to the host verification task")
            if metadata.get("model_reconciliation_required"):
                raise HTTPException(409, "Previous model usage requires reconciliation")
            calls = metadata.setdefault("model_requests", {})
            if any(item.get("state") in {"reserved", "unknown"} for item in calls.values()):
                raise HTTPException(409, "A model request is still in progress or unconfirmed")
            maximum_calls = config.get("max_model_calls", route.max_model_calls)
            if type(maximum_calls) is not int or not 0 < maximum_calls <= 1000:
                raise HTTPException(409, "Task model-call limit is invalid")
            if len(calls) >= maximum_calls:
                raise _ModelCallLimitReached(maximum_calls, len(calls))
            control = metadata.get("react_progress") or {}
            phase = "repair" if control.get("repairing") else "execution"
            if not verification_job and control:
                limit = control["limits"][phase]
                used = sum(
                    row.get("execution_phase", row.get("purpose")) == phase
                    for row in calls.values()
                )
                if used >= limit:
                    handoff = phase == "execution" and control["limits"]["repair"] > 0
                    raise _ModelCallLimitReached(
                        limit,
                        used,
                        "react_execution_phase_exhausted"
                        if handoff
                        else f"react_{phase}_budget_exhausted",
                    )
            reserved_calls, reserved_cost = verification_reserve(metadata)
            if verification_job:
                if metadata.get("verification_budget") and reserved_calls <= 0:
                    raise HTTPException(429, "Independent verification call budget is exhausted")
            elif len(calls) + reserved_calls >= maximum_calls:
                if not control:
                    raise HTTPException(
                        429, "Remaining model calls are reserved for independent verification"
                    )
                raise _ModelCallLimitReached(
                    maximum_calls - reserved_calls,
                    len(calls),
                    f"react_{phase}_budget_exhausted",
                )
            held = int(run.metadata.get("reserved_cost_units") or 0)
            if budget_exceeded_payload(
                run,
                additional_cost_units=held + reserve + (0 if verification_job else reserved_cost),
                scope="xiaox_model",
            ):
                raise HTTPException(402, "Task model budget is insufficient")
            run.metadata["reserved_cost_units"] = held + reserve
            calls[request_id] = {
                "state": "reserved",
                "reserved_units": reserve,
                "model": route.model,
                "expected_response_model": route.response_model,
                "gateway_kind": route.gateway_kind,
                "provider_id": route.provider_id,
                "request_group": request_group or request_id,
                "attempt": attempt,
                "started_at": time.time(),
                "trace_id": ensure_run_trace(run, live=False)["trace_id"],
                "route_identity": route.identity,
                "receipt_scope": {
                    name: getattr(route, name)
                    for name in (
                        "provider_id",
                        "model",
                        "response_model",
                        "config_revision",
                        "key_source",
                    )
                },
                **({"observation": observation} if observation else {}),
                "purpose": "verification" if verification_job else "execution",
                "execution_phase": "verification"
                if verification_job
                else (
                    "repair" if metadata.get("react_progress", {}).get("repairing") else "execution"
                ),
                **(
                    {
                        "verification_job_id": verification_job,
                        "verification_input_digest": (run.metadata.get(JOB_KEY) or {}).get(
                            "input_digest"
                        ),
                        "verification_version": (run.metadata.get(JOB_KEY) or {}).get("version"),
                    }
                    if verification_job
                    else {}
                ),
            }
            run.add_event(
                "runtime.model.started",
                data={"model_request_id": request_id, "purpose": calls[request_id]["purpose"]},
            )
            # The SDK thread keeps its original logical model. Persist the
            # actual route so its later opaque history never goes back to the
            # previous provider after a successful switch or a host restart.
            run.metadata["runtime_effective_model_route"] = route.identity

        try:
            store.update(binding.run_id, claim, generation=binding.metadata.get("generation"))
        except _ModelCallLimitReached as exhausted:
            # The refusal itself must survive as a readable host fact, so the
            # reason is committed before the request is rejected.
            max_model_calls = exhausted.max_model_calls
            used_model_calls = exhausted.used_model_calls

            def record(run: Any, metadata: dict[str, Any]) -> None:
                metadata["model_call_limit"] = {
                    "reason": exhausted_reason,
                    "max_model_calls": max_model_calls,
                    "used_model_calls": used_model_calls,
                }

            exhausted_reason = exhausted.reason
            store.update(binding.run_id, record, generation=binding.metadata.get("generation"))
            raise HTTPException(429, "Task model-call limit reached") from exhausted
        return binding, reserve


def _finish(
    store: Any,
    run_id: str,
    request_id: str,
    *,
    usage: dict[str, int] | None,
    usage_key: str,
    state: str = "completed",
    market_route: ModelRoute | PlatformModelReceiptScope | None = None,
    platform_receipt: Any = None,
    observation: dict[str, Any] | None = None,
    verification_response: dict[str, Any] | None = None,
    reconciled_response: dict[str, Any] | None = None,
    reconciled_rejection: dict[str, Any] | None = None,
) -> None:
    from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
    from app.application.agent_orchestrator.run_models import LLMCall
    from app.infrastructure.billing.model_reservation import settle_model_usage

    settled: dict[str, Any] | None
    if market_route is not None and usage is not None:
        from app.infrastructure.billing.model_reservation import record_platform_model_usage

        with _settlement_storage("binding_read"):
            binding = store.get(run_id)
        with _settlement_storage("usage_ledger"):
            settled = record_platform_model_usage(
                usage_key=usage_key,
                run_id=run_id,
                user_id=binding.run.user_id,
                request_id=request_id,
                route=market_route,
                usage=usage,
                receipt=platform_receipt,
            )
    else:
        with _settlement_storage("usage_ledger"):
            settled = settle_model_usage(usage_key, usage) if usage is not None else None

    def finish(run: Any, metadata: dict[str, Any]) -> None:
        call = metadata["model_requests"][request_id]
        if observation:
            call["observation"] = observation
        terminal = call.get("state") in {"completed", "failed"}
        if not terminal:
            call.update(
                state=state if settled else "unknown",
                usage_key=usage_key,
                finished_at=time.time(),
            )
        if settled is None or usage is None:
            if not terminal:
                metadata["model_reconciliation_required"] = True
            return
        # A late receipt for this exact request can resolve its model hold. It
        # cannot clear another request's uncertainty or any business-effect gate.
        metadata["model_reconciliation_required"] = any(
            item.get("state") in {"reserved", "unknown"}
            for item in metadata["model_requests"].values()
        )
        if reconciled_response is not None:
            call.setdefault("reconciled_response", reconciled_response)
            call.update(
                observed_model=reconciled_response["model"],
                model_identity_verified=True,
                gateway_attempts_verified=True,
            )
            if not terminal:
                run.add_event(
                    "runtime.model.reconciled",
                    "已核对原模型终态与计量，未重放调用",
                    {"model_request_id": request_id},
                )
        if reconciled_rejection is not None:
            call.setdefault("reconciled_rejection", reconciled_rejection)
            call["diagnostic"] = {
                **(call.get("diagnostic") or {}),
                "failure_kind": "model_schema_rejected",
                "failure_reason": "所选模型拒绝了结构化输出格式。",
                "outcome": "not_started",
                "retryable": False,
            }
        if (
            verification_response is not None
            and call.get("purpose") == "verification"
            and call.get("state") == state == "completed"
        ):
            from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest

            # Keep a settled read-only response before publishing to the caller.
            # Losing that connection never requires a second metered request.
            digest = canonical_digest(verification_response)
            if "verification_response" in call and (
                call.get("verification_response_digest") != digest
                or canonical_digest(call["verification_response"]) != digest
            ):
                raise ModelGatewayContractError(
                    "verification_response_conflict",
                    "A settled verification response cannot change",
                )
            call.setdefault("verification_response", verification_response)
            call.setdefault("verification_response_digest", digest)
        if terminal:
            return
        call.update(usage=usage, cost_units=settled["cost_units"])
        diagnostic = call.get("diagnostic") or {}
        run.add_event(
            "runtime.model.completed" if state == "completed" else "runtime.model.failed",
            data={
                "model_request_id": request_id,
                "purpose": call.get("purpose"),
                **{k: diagnostic[k] for k in ("failure_kind", "outcome") if k in diagnostic},
            },
        )
        if state == "completed":
            for key in ("runtime_failure_kind", "runtime_failure_reason", "runtime_failure_stage"):
                run.metadata.pop(key, None)
        run.metadata["reserved_cost_units"] = max(
            0,
            int(run.metadata.get("reserved_cost_units") or 0) - call["reserved_units"],
        )
        run.llm_calls.append(
            LLMCall(
                call_id=request_id,
                provider_id=call["provider_id"],
                model=call.get("observed_model") or call["model"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                cost_units=settled["cost_units"],
                billing_status=settled.get("billing_status", ""),
                status="completed" if state == "completed" else "failed",
                metadata={
                    "usage_key": usage_key,
                    "source": "xiaox.model_gateway",
                    "requested_model": call["model"],
                    "observed_model": call.get("observed_model"),
                    "model_identity_verified": call.get("model_identity_verified") is True,
                    "gateway_attempts_verified": call.get("gateway_attempts_verified") is True,
                },
            )
        )
        run.metadata["ai_cost_units_total"] = (
            int(run.metadata.get("ai_cost_units_total") or 0) + settled["cost_units"]
        )
        refresh_ai_budget_metadata(run)

    with _settlement_storage("run_projection"):
        store.update(run_id, finish)


class _ModelSettlementStorageError(RuntimeError):
    code = "model_settlement_storage_failed"

    def __init__(self, stage: str, error: BaseException) -> None:
        super().__init__("Model settlement could not be persisted")
        self.diagnostic: dict[str, str | int] = {
            "storage_stage": stage,
            "error_type": type(error).__name__,
        }
        original = error.orig if isinstance(error, DBAPIError) else error
        if isinstance(original, sqlite3.Error):
            code = getattr(original, "sqlite_errorcode", None)
            name = getattr(original, "sqlite_errorname", None)
            if type(code) is int and 0 < code <= 0x7FFFFFFF:
                self.diagnostic["sqlite_error_code"] = code
            if (
                isinstance(name, str)
                and len(name) <= 64
                and name.startswith("SQLITE_")
                and name.isascii()
                and name.isidentifier()
            ):
                self.diagnostic["sqlite_error_name"] = name


@contextmanager
def _settlement_storage(stage: str) -> Iterator[None]:
    try:
        yield
    except (sqlite3.Error, DBAPIError) as error:
        # DBAPIError renders bound SQL parameters in its traceback.
        raise _ModelSettlementStorageError(stage, error) from None


@router.post(MODEL_PATH)
async def forward_responses(request: Request):
    import anyio

    from app.domain.model_admission_errors import (
        ModelCircuitOpenError,
        ModelConcurrencyLimitError,
        ModelRateLimitError,
    )
    from app.infrastructure.billing.model_reservation import (
        ModelReservationError,
        reserve_model_usage,
    )
    from app.infrastructure.llm.model_admission import model_call_slot, model_rate_limit_scope
    from app.infrastructure.xiaox.binding import XiaoxBindingError
    from app.utils.operational_errors import BOUNDARY_ERRORS

    store = request.app.state.xiaox_binding_store
    primary: ModelRoute = request.app.state.xiaox_model_route
    route = primary
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "A run-bound model token is required")
    token = auth[7:]
    try:
        binding = await anyio.to_thread.run_sync(
            lambda: store.authenticate(token, audience="model")
        )
    except XiaoxBindingError as exc:
        raise HTTPException(403, "Runtime model authorization is invalid") from exc
    if binding.run_id != getattr(request.app.state, "xiaox_run_id", None):
        raise HTTPException(403, "Runtime model authorization belongs to another task")
    routes = tuple(getattr(request.app.state, "xiaox_model_routes", (primary,)))
    authorized = (binding.metadata.get("runtime_config") or {}).get(
        "authorized_model_routes", [primary.identity]
    )
    if (
        not 1 <= len(routes) <= 3
        or routes[0] != primary
        or [item.identity for item in routes] != authorized
    ):
        raise HTTPException(409, "Authorized model routes no longer match this task")
    active = binding.run.metadata.get("runtime_effective_model_route", primary.identity)
    if active not in authorized:
        raise HTTPException(409, "The task's effective model route is no longer authorized")
    route_index = authorized.index(active)
    expected_active_route = active
    route = routes[route_index]
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > primary.max_request_bytes:
            raise HTTPException(413, "Model request is too large")
    try:
        requested_body = json.loads(raw)
        logical_body = _prepare_body(requested_body, primary)  # Keep the SDK's original contract.
        requested_body["max_output_tokens"] = logical_body["max_output_tokens"]
        body = _prepare_body({**requested_body, "model": route.model}, route)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid Responses request") from exc
    verification_job = request.headers.get(JOB_HEADER, "")
    from app.domain.task_lifecycle.react_progress import (
        CONTROL_KEY,
        receipt_facts,
        requires_actions,
    )

    control = binding.metadata.get(CONTROL_KEY) or {}
    if not verification_job and control.get("repairing"):
        target = control.get("route_switch_target")
        if target and target != active:
            if target not in authorized or authorized.index(target) != route_index + 1:
                raise HTTPException(409, "Repair model target no longer matches authorized routes")
            if not _portable_fallback_body(requested_body):
                raise HTTPException(
                    409, "Repair context is not portable to the authorized alternate model"
                )
            route_index = authorized.index(target)
            route = routes[route_index]
            body = _prepare_body({**requested_body, "model": route.model}, route)
    if not verification_job:
        from app.domain.task_lifecycle.agent_runtime_results import (
            receipt_settled_failure,
            receipt_verified,
        )

        rows = [
            {"call_id": key, **value}
            for key, value in (binding.metadata.get("calls") or {}).items()
        ]
        if (
            requires_actions(control)
            or binding.run.metadata.get("runtime_completion_mode") == "business"
        ) and not (
            binding.metadata.get("waiting_input")
            or any(not (receipt_verified(row) or receipt_settled_failure(row)) for row in rows)
            or (set(receipt_facts(rows)) - set(control.get("facts", [])))
        ):
            if not body.get("tools"):
                raise HTTPException(409, "The current repair requires authorized host tools")
            body["tool_choice"] = "required"

    if verification_job or binding.metadata.get("active_phase") == "verification":
        if not verification_job or verification_job != active_verification_job_id(
            binding.run, binding.metadata
        ):
            raise HTTPException(403, "Model request is not bound to the host verification task")
        if body.get("tools") or body.get("stream"):
            raise HTTPException(
                400, "Independent verification must be a non-streaming tool-free request"
            )
    route.token()  # Validate the account credential without persisting it.
    request_group = "request_" + uuid.uuid4().hex
    request_id = "model_" + uuid.uuid4().hex
    usage_key = f"xiaox:{binding.run_id}:{request_id}"
    observation = None
    try:
        from app.application.agent_orchestrator.task_context import ensure_run_trace
        from app.infrastructure.llm.genai_telemetry import ModelRequestObservation

        observation = ModelRequestObservation(
            context=ensure_run_trace(binding.run, live=False),
            run_id=binding.run_id,
            provider_id=route.provider_id,
            model=route.model,
            request_group=request_group,
        )
    except BOUNDARY_ERRORS as exc:
        logger.warning("model trace initialization unavailable (%s)", type(exc).__name__)

    def observe(method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            if observation is not None:
                if method == "attempt":
                    # One span owns this request group; each physical attempt
                    # records its actual qualified route, including fallback.
                    observation.span.attributes.update(
                        {
                            "gen_ai.system": route.provider_id,
                            "gen_ai.request.model": route.model,
                            "xcagi.route_identity": route.identity,
                        }
                    )
                    observation.span.add_event(
                        "gen_ai.request.route",
                        {
                            "request_id": args[0],
                            "attempt": args[1],
                            "provider_id": route.provider_id,
                            "model": route.model,
                            "route_identity": route.identity,
                        },
                    )
                value = getattr(observation, method)(*args, **kwargs)
                if method == "snapshot" and isinstance(value, dict):
                    return {
                        **value,
                        "provider_id": route.provider_id,
                        "model": route.model,
                        "route_identity": route.identity,
                    }
                return value
        except BOUNDARY_ERRORS as exc:
            logger.warning("model observation %s unavailable (%s)", method, type(exc).__name__)
        return None

    async def transport_trace(name: str, info: dict[str, Any]) -> None:
        try:
            if observation is not None:
                await observation.transport_trace(name, info)
        except BOUNDARY_ERRORS as exc:
            logger.warning("model transport observation unavailable (%s)", type(exc).__name__)

    stack = ExitStack()
    client = None
    upstream = None
    claimed = False
    reserved = False
    network_started = False
    finished = False
    streaming_handoff = False
    cleanup_started = False
    slot_failure: BaseException | None = None
    platform_receipt: Any = None
    request_phase = "admission"
    observed_requests: set[str] = set()

    def finish_usage(*args: Any, **kwargs: Any) -> None:
        _finish(
            *args,
            **kwargs,
            market_route=route if route.gateway_kind == "market" else None,
            platform_receipt=platform_receipt,
            observation=observe("snapshot"),
        )
        observe("settle", usage=kwargs.get("usage"), state=kwargs.get("state", "completed"))

    def close_slot(error: BaseException | None = None) -> None:
        stack.__exit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )

    def mark_unknown() -> None:
        if claimed:
            finish_usage(store, binding.run_id, request_id, usage=None, usage_key=usage_key)

    async def close_transport(resource: Any, cleanup_deadline: float | None = None) -> None:
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + model_phase_timeout_seconds("cleanup")
        # Also used between attempts: closing a failed transport is part of
        # bounded recovery and may never prevent the next deadline check.
        with anyio.move_on_after(max(0.0, cleanup_deadline - time.monotonic())) as closing:
            await resource.aclose()
        if closing.cancel_called:
            logger.warning("Xiaox model transport cleanup deadline exceeded")

    async def close_resources(
        error: BaseException | None, settle: Callable[[], None] | None = None
    ) -> None:
        nonlocal cleanup_started
        if cleanup_started:
            return
        cleanup_started = True
        interrupted = sys.exception()
        cleanup_deadline = time.monotonic() + model_phase_timeout_seconds("cleanup")

        try:
            with anyio.CancelScope(shield=True):
                async with AsyncExitStack() as cleanup:
                    cleanup.callback(close_slot, error or interrupted)
                    if client is not None:
                        cleanup.push_async_callback(close_transport, client, cleanup_deadline)
                    if upstream is not None:
                        cleanup.push_async_callback(close_transport, upstream, cleanup_deadline)
                    if settle is not None:
                        await anyio.to_thread.run_sync(settle)
        except BOUNDARY_ERRORS as cleanup_error:
            # Request cancellation remains authoritative even if receipt storage
            # or a transport close fails; every registered cleanup still runs.
            if isinstance(interrupted, anyio.get_cancelled_exc_class()):
                raise interrupted
            if isinstance(cleanup_error, _ModelSettlementStorageError) and interrupted is not None:
                logger.warning("Xiaox model settlement cleanup remains unconfirmed")
                return  # Keep the original HTTP refusal and its diagnostic.
            raise
        finally:
            observe("finish", error or interrupted or sys.exception())
            final_observation = observe("snapshot")
            if observed_requests and final_observation:

                def record_observation(_run: Any, metadata: dict[str, Any]) -> None:
                    # Group timing is shared; each durable attempt retains its
                    # own route. Observation never changes usage or task state.
                    for key, call in metadata.get("model_requests", {}).items():
                        if key in observed_requests and call.get("request_group") == request_group:
                            call["observation"] = {
                                **final_observation,
                                "provider_id": call.get("provider_id"),
                                "model": call.get("model"),
                                "route_identity": call.get("route_identity"),
                                "request_id": key,
                                "attempt": call.get("attempt"),
                            }

                try:
                    with anyio.move_on_after(
                        max(0.0, cleanup_deadline - time.monotonic()), shield=True
                    ) as observation_cleanup:
                        await anyio.to_thread.run_sync(
                            lambda: store.update(binding.run_id, record_observation),
                            abandon_on_cancel=True,
                        )
                    if observation_cleanup.cancel_called:
                        logger.warning("model observation persistence cleanup deadline exceeded")
                except BOUNDARY_ERRORS as exc:
                    logger.warning(
                        "model observation persistence unavailable (%s)", type(exc).__name__
                    )

    def choose_next_route() -> None:
        nonlocal route_index, route, body
        if route_index + 1 < len(routes) and _portable_fallback_body(requested_body):
            route_index += 1
            route = routes[route_index]
            body = _prepare_body({**requested_body, "model": route.model}, route)
            route.token()

    try:
        # All attempts share one absolute clock. An expired task still closes
        # its observation, without admitting a model call or resetting budget.
        inference_deadline = deadline = model_request_deadline(binding, route)
        from app.infrastructure.llm.retry_policy import (
            MODEL_SCHEMA_REJECTED,
            is_safe_transport_retry,
            model_failure_details,
        )

        async def record_failure(
            error: BaseException,
            *,
            output_started: bool = False,
            upstream_error: str = "",
            schema_rejected: bool = False,
            settled: bool = False,
            stream_phase: str | None = None,
            stream_frame: int | None = None,
        ) -> None:
            details = model_failure_details(
                error,
                stage="xiaox.responses",
                attempt=attempt,
                elapsed_ms=(time.monotonic() - attempt_started) * 1000,
                output_started=output_started,
                stream_phase=stream_phase,
                stream_frame=stream_frame,
            )
            timeout_phase = next(
                (
                    name
                    for name, cls in (
                        ("connect", httpx.ConnectTimeout),
                        ("pool", httpx.PoolTimeout),
                        ("write", httpx.WriteTimeout),
                        ("read", httpx.ReadTimeout),
                    )
                    if isinstance(error, cls)
                ),
                request_phase,
            )
            details["request_phase"] = timeout_phase
            # 保留截断后的上游原因，供只读核对；响应体不是权限依据。
            if upstream_error:
                details["upstream_error"] = upstream_error[:500]
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                details.update(outcome="not_started", retryable=True)
            if schema_rejected:
                details.update(
                    failure_kind="model_schema_rejected",
                    failure_reason="所选模型拒绝了结构化输出格式。",
                    outcome="not_started",
                )
            if settled:
                details["outcome"] = "settled"
            if isinstance(error, ModelGatewayContractError):
                details.update(failure_kind=error.code, failure_reason=str(error), retryable=False)
            if isinstance(error, _ModelSettlementStorageError):
                details.update(
                    error.diagnostic,
                    failure_kind=error.code,
                    failure_reason=str(error),
                )
                logger.warning(
                    "Xiaox settlement storage phase=%s driver_result=%s run=%s",
                    error.diagnostic["storage_stage"],
                    error.diagnostic.get("sqlite_error_name", "unavailable"),
                    binding.run_id,
                )
            if isinstance(error, _ModelOutputItemError):
                details["response_item"] = error.diagnostic

            def record(run: Any, metadata: dict[str, Any]) -> None:
                call = metadata.get("model_requests", {}).get(request_id)
                if call is not None:
                    call["diagnostic"] = details
                    call["duration_ms"] = details["elapsed_ms"]
                run.metadata["runtime_failure_kind"] = details["failure_kind"]
                run.metadata["runtime_failure_reason"] = details["failure_reason"]
                run.metadata["runtime_failure_stage"] = "model"
                run.add_event(
                    "runtime.model.failure",
                    details["failure_reason"],
                    {
                        **details,
                        "model_request_id": request_id,
                        "purpose": (call or {}).get("purpose"),
                    },
                )

            await anyio.to_thread.run_sync(lambda: store.update(binding.run_id, record))

        async def observe_identity(response: Any) -> None:
            nonlocal platform_receipt
            if not isinstance(response, dict):
                raise ModelGatewayContractError(
                    "model_identity_missing", "Gateway response identity is missing"
                )
            if route.gateway_kind == "market" and response.get("status") in _TERMINAL_STATES:
                platform_receipt = response.get("xcagi")
                if not isinstance(platform_receipt, dict):
                    raise ModelReservationError("Platform terminal settlement receipt is missing")
            raw = response.get("model")
            observed = (
                raw if isinstance(raw, str) and 0 < len(raw) <= 256 and raw.isprintable() else None
            )
            matches = observed == route.response_model

            def record(run: Any, metadata: dict[str, Any]) -> None:
                call = metadata["model_requests"][request_id]
                call.update(observed_model=observed, model_identity_verified=matches)
                response_id = response.get("id")
                if (
                    isinstance(response_id, str)
                    and len(response_id) <= 256
                    and response_id.isprintable()
                ):
                    call["provider_response_id"] = response_id
                call["duration_ms"] = round((time.monotonic() - attempt_started) * 1000, 1)

            await anyio.to_thread.run_sync(lambda: store.update(binding.run_id, record))
            if response.get("fallback_used") or response.get("_fallback_used"):
                raise ModelGatewayContractError(
                    "gateway_attempts_unverified", "Gateway reported an unauthorized fallback"
                )
            if not matches:
                # A complete final response can have known usage despite a
                # wrong model. Account for that actual attempt, reject all its
                # output, and retain the observed identity in the same ledger.
                usage = response_usage(response)
                if response.get("status") in _TERMINAL_STATES and usage is not None:
                    await anyio.to_thread.run_sync(
                        lambda: finish_usage(
                            store,
                            binding.run_id,
                            request_id,
                            usage=usage,
                            usage_key=usage_key,
                            state="failed",
                        )
                    )
                raise ModelGatewayContractError(
                    "model_identity_mismatch",
                    "Gateway returned a missing or unqualified model identity",
                )

        for attempt in range(1, 4):
            attempt_started = time.monotonic()
            request_id = "model_" + uuid.uuid4().hex
            usage_key = f"xiaox:{binding.run_id}:{request_id}"
            observe("attempt", request_id, attempt)
            claimed = reserved = network_started = finished = False
            platform_receipt = None
            slot_failure = None
            binding = await anyio.to_thread.run_sync(
                lambda: store.authenticate(token, audience="model")
            )
            _remaining(binding)
            admission_started = time.perf_counter()
            try:
                with model_rate_limit_scope(binding.context):
                    stack.enter_context(
                        model_call_slot(
                            SimpleNamespace(
                                provider_id=route.provider_id,
                                model=route.model,
                                route_identity=route.identity,
                            ),
                            profile="xiaox",
                        )
                    )
            finally:
                observe(
                    "add_duration", "admission", (time.perf_counter() - admission_started) * 1000
                )
            await anyio.to_thread.run_sync(
                lambda: _claim(
                    store,
                    token,
                    route,
                    request_id,
                    request_group=request_group,
                    attempt=attempt,
                    expected_route_identity=expected_active_route,
                    observation=observe("snapshot"),
                    verification_job=verification_job,
                )
            )
            claimed = True
            observed_requests.add(request_id)
            expected_active_route = route.identity
            if route.gateway_kind != "market":
                await anyio.to_thread.run_sync(
                    lambda: reserve_model_usage(
                        usage_key=usage_key,
                        run_id=binding.run_id,
                        user_id=binding.run.user_id,
                        provider_id=route.provider_id,
                        model=route.model,
                        token_ceiling=route.effective_context_window,
                    )
                )
            # The platform reserves and settles its wallet. _claim still checks
            # the original task's accumulated budget and model-call ceiling.
            reserved = True
            await anyio.to_thread.run_sync(lambda: store.authenticate(token, audience="model"))
            client_factory = getattr(request.app.state, "xiaox_http_client_factory", None)
            attempt_budget = request_remaining(deadline)
            client_options: dict[str, Any] = {
                # HTTPX phase timeout stays bounded by the one absolute clock;
                # it is a transport guard, not a second budget.
                "timeout": httpx.Timeout(
                    **{
                        phase: min(
                            model_phase_timeout_seconds(phase, attempt_budget), attempt_budget
                        )
                        for phase in ("connect", "read", "write", "pool")
                    }
                ),
                "trust_env": False,
                "follow_redirects": False,
            }
            if client_factory is None:
                from app.infrastructure.xiaox.qualification import IndependentModelTransport

                client_options["transport"] = IndependentModelTransport(route)
                client_factory = httpx.AsyncClient
            client = client_factory(**client_options)
            headers = {"Accept": "text/event-stream" if body.get("stream") else "application/json"}
            headers.update(route.headers(request_id))
            if route.gateway_kind == "market":
                headers["X-XCMax-Request-Deadline-Ms"] = str(
                    int((time.time() + request_remaining(deadline)) * 1000)
                )
            headers.update(observe("headers") or {})
            outbound = client.build_request(
                "POST",
                route.base_url + "/responses",
                headers=headers,
                json=body,
            )
            outbound.extensions["trace"] = transport_trace
            network_started = True
            request_phase = "response"
            try:
                with anyio.fail_after(
                    min(
                        model_phase_timeout_seconds("response", attempt_budget),
                        request_remaining(deadline),
                    )
                ):
                    upstream = await client.send(outbound, stream=True)
            except httpx.HTTPError as exc:
                slot_failure = exc
                await record_failure(exc)
                if not is_safe_transport_retry(exc):
                    raise
                await anyio.to_thread.run_sync(
                    lambda: finish_usage(
                        store,
                        binding.run_id,
                        request_id,
                        usage=_ZERO_USAGE,
                        usage_key=usage_key,
                        state="failed",
                    )
                )
                finished = True
                if attempt == 3:
                    raise
                await close_transport(client)
                client = None
                close_slot(slot_failure)
                delay = retry_delay(attempt)
                if request_remaining(deadline) <= delay:
                    raise HTTPException(
                        408, "Task deadline cannot admit another model attempt"
                    ) from exc
                request_phase = "backoff"
                if not await _wait_for_model_retry(request, delay):
                    return Response(status_code=499)
                choose_next_route()
                continue
            request_phase = "inference"
            inference_deadline = min(
                deadline,
                time.monotonic()
                + model_phase_timeout_seconds("inference", request_remaining(deadline)),
            )
            headers_ms = round((time.monotonic() - attempt_started) * 1000, 1)
            await anyio.to_thread.run_sync(
                lambda: store.update(
                    binding.run_id,
                    lambda _run, metadata: metadata["model_requests"][request_id].update(
                        response_headers_ms=headers_ms
                    ),
                )
            )
            if route.gateway_kind in {"litellm", "market"} and upstream.status_code < 300:
                expected_headers = (
                    {"x-xcmax-upstream-attempts": "1", "x-xcmax-upstream-fallbacks": "0"}
                    if route.gateway_kind == "market"
                    else {"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"}
                )
                verified = all(
                    upstream.headers.get_list(name) == [value]
                    for name, value in expected_headers.items()
                )
                await anyio.to_thread.run_sync(
                    lambda: store.update(
                        binding.run_id,
                        lambda _run, metadata: metadata["model_requests"][request_id].update(
                            gateway_attempts_verified=verified
                        ),
                    )
                )
                if not verified:
                    raise ModelGatewayContractError(
                        "gateway_attempts_unverified",
                        "Gateway did not prove zero hidden retries and fallbacks",
                    )
            if upstream.status_code < 300:
                break
            slot_failure = httpx.HTTPStatusError(
                "Qualified gateway rejected request", request=outbound, response=upstream
            )
            upstream_error = ""
            try:
                # Non-2xx bodies can drip bytes forever, just like a successful
                # response. They consume the original header/retry/body clock.
                with anyio.fail_after(request_remaining(inference_deadline)):
                    await upstream.aread()
                upstream_error = upstream.text
            except TimeoutError:
                # AnyIO's absolute timeout is also an OSError; do not erase it
                # while treating an unreadable provider diagnostic as optional.
                raise
            except (httpx.HTTPError, UnicodeDecodeError, OSError):
                upstream_error = ""
            schema_rejected = False
            if route.gateway_kind == "market" and upstream.status_code == 422:
                try:
                    envelope = upstream.json()
                    detail = envelope.get("detail") if isinstance(envelope, dict) else None
                    schema_rejected = (
                        isinstance(detail, dict) and detail.get("code") == MODEL_SCHEMA_REJECTED
                    )
                except (ValueError, UnicodeDecodeError):
                    pass
            await record_failure(
                slot_failure, upstream_error=upstream_error, schema_rejected=schema_rejected
            )
            # Explicit rejection has no generated completion. A 5xx/408 can
            # hide a started model request and remains unresolved, without replay.
            definite = (
                400 <= upstream.status_code < 500
                and upstream.status_code != 408
                and not (route.gateway_kind == "market" and upstream.status_code == 409)
            )
            await anyio.to_thread.run_sync(
                lambda: finish_usage(
                    store,
                    binding.run_id,
                    request_id,
                    usage=_ZERO_USAGE if definite else None,
                    usage_key=usage_key,
                    state="failed",
                )
            )
            finished = True
            retry_after = (
                _retry_after_seconds(upstream.headers) if upstream.status_code == 429 else None
            )
            if upstream.status_code == 429 and attempt < 3:
                delay = retry_delay(attempt, upstream.headers.get("retry-after"))
                if request_remaining(deadline) > delay:
                    cleanup_deadline = time.monotonic() + model_phase_timeout_seconds("cleanup")
                    await close_transport(upstream, cleanup_deadline)
                    await close_transport(client, cleanup_deadline)
                    upstream = client = None
                    close_slot(slot_failure)
                    request_phase = "backoff"
                    if not await _wait_for_model_retry(request, delay):
                        return Response(status_code=499)
                    choose_next_route()
                    continue
            return JSONResponse(
                {
                    "error": {
                        "message": "所选模型拒绝了结构化输出格式。"
                        if schema_rejected
                        else "Qualified model gateway request failed",
                        "type": "upstream_error",
                        **({"code": MODEL_SCHEMA_REJECTED} if schema_rejected else {}),
                    }
                },
                status_code=upstream.status_code if definite else 502,
                headers={"Retry-After": str(math.ceil(retry_after))}
                if retry_after is not None
                else None,
            )
        assert upstream is not None and client is not None
        slot_failure = None
        if not body.get("stream"):
            with anyio.fail_after(request_remaining(inference_deadline)):
                response = json.loads(await upstream.aread())
            await observe_identity(response)
            _validate_model_output(response)
            status = response.get("status")
            if status not in _TERMINAL_STATES:
                raise ModelGatewayContractError(
                    "model_terminal_state_invalid", "Gateway response has no valid terminal state"
                )
            usage = response_usage(response)
            await anyio.to_thread.run_sync(
                lambda: finish_usage(
                    store,
                    binding.run_id,
                    request_id,
                    usage=usage,
                    usage_key=usage_key,
                    state="completed" if status == "completed" else "failed",
                    verification_response=response if verification_job else None,
                )
            )
            finished = True
            if usage is None:
                raise HTTPException(502, "Gateway response omitted verified usage")
            current = await anyio.to_thread.run_sync(
                lambda: store.authenticate(token, audience="model")
            )
            _remaining(current)
            if status != "completed":
                error = ModelGatewayContractError(
                    f"model_response_{status}", f"Gateway response ended as {status}"
                )
                await record_failure(error, settled=True)
                if any(item.get("type") == "function_call" for item in response.get("output", [])):
                    raise error
            return JSONResponse(response)

        async def events() -> AsyncGenerator[bytes, None]:
            completed = False
            terminal = False
            failure = None
            identity_verified = False
            output_visible = False
            held: list[bytes] = []
            held_bytes = 0
            hold_tools = False
            stream_phase = "event_shape"
            stream_frame = 0
            try:
                # The stream closes on the same absolute clock that bounded
                # the header wait; downstream slowness cannot extend it, and
                # a reconnect never re-issues this request.
                with anyio.fail_after(request_remaining(inference_deadline)):
                    async for event in EventSource(upstream).aiter_sse():
                        if event.data == "[DONE]":
                            continue
                        stream_frame += 1
                        stream_phase = "event_shape"
                        payload = json.loads(event.data)
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid model event")
                        stream_phase = "event_identity"
                        kind = payload.get("type", event.event)
                        if "response" in payload:
                            await observe_identity(payload["response"])
                            identity_verified = True
                        if not identity_verified:
                            raise ModelGatewayContractError(
                                "model_identity_missing",
                                "Gateway streamed output before its model identity",
                            )
                        if kind in {"response.output_item.added", "response.output_item.done"}:
                            stream_phase = "delta_item"
                            _validate_output_item(payload.get("item"))
                            if (payload.get("item") or {}).get("type") == "function_call":
                                hold_tools = True
                        if str(kind).startswith("response.function_call_arguments."):
                            hold_tools = True
                        if kind in {f"response.{status}" for status in _TERMINAL_STATES}:
                            stream_phase = "terminal_output"
                            response = payload.get("response") or {}
                            _validate_model_output(response)
                            status = response.get("status")
                            if kind != f"response.{status}":
                                raise ModelGatewayContractError(
                                    "model_terminal_state_invalid",
                                    "Gateway terminal event does not match its response state",
                                )
                            stream_phase = "settlement"
                            usage = response_usage(response)
                            await anyio.to_thread.run_sync(
                                lambda: finish_usage(
                                    store,
                                    binding.run_id,
                                    request_id,
                                    usage=usage,
                                    usage_key=usage_key,
                                    state="completed" if status == "completed" else "failed",
                                )
                            )
                            if usage is None:
                                raise ModelReservationError("Gateway stream omitted verified usage")
                            terminal = True
                            completed = status == "completed"
                            if not completed:
                                error = ModelGatewayContractError(
                                    f"model_response_{status}",
                                    f"Gateway response ended as {status}",
                                )
                                await record_failure(
                                    error, output_started=output_visible, settled=True
                                )
                                if any(
                                    item.get("type") == "function_call"
                                    for item in response.get("output", [])
                                ):
                                    raise error
                        # Re-check token/session revocation before tool proposals become visible.
                        if kind == "response.output_item.done" or terminal:
                            current = await anyio.to_thread.run_sync(
                                lambda: store.authenticate(token, audience="model")
                            )
                            _remaining(current)
                        frame = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
                        if terminal and not completed:
                            # Preserve the provider's known failure for bounded
                            # recovery, without releasing any earlier proposal.
                            output_visible = True
                            yield frame
                            break
                        if hold_tools:
                            # Keep order from the first tool proposal onward.
                            # A final identity/usage drift must not arrive after
                            # the runtime has already been given executable work.
                            held_bytes += len(frame)
                            if held_bytes > route.max_request_bytes:
                                raise ModelGatewayContractError(
                                    "model_tool_stream_too_large",
                                    "Model tool stream exceeded its bounded buffer",
                                )
                            held.append(frame)
                            if completed:
                                output_visible = True
                                for item_frame in held:
                                    yield item_frame
                        else:
                            output_visible = True
                            yield frame
                        if completed:
                            break
                    if not terminal:
                        raise ModelReservationError("Gateway stream ended without completion")
            except BOUNDARY_ERRORS as exc:
                failure = exc
                await record_failure(
                    exc,
                    output_started=output_visible,
                    stream_phase=stream_phase,
                    stream_frame=stream_frame,
                )
                error_payload = {
                    "code": getattr(exc, "code", "model_stream_error"),
                    "message": (
                        "Model stream output was rejected"
                        if terminal
                        else "Model stream requires reconciliation"
                    ),
                }
                yield f"data: {json.dumps({'type': 'error', 'error': error_payload})}\n\n".encode()
            finally:
                await close_resources(failure, mark_unknown if not terminal else None)

        finished = True  # Streaming iterator now owns cleanup and settlement.
        streaming_handoff = True
        event_stream = events()

        class ModelStreamingResponse(StreamingResponse):
            async def stream_response(self, send: Send) -> None:
                # The generator owns an AnyIO deadline scope; close it in the
                # same streaming task even when the downstream send fails.
                async with aclosing(event_stream):
                    await super().stream_response(send)

            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    # A failed response start never enters the body generator.
                    await close_resources(None, mark_unknown)

        return ModelStreamingResponse(
            event_stream, media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )
    except ModelReservationError as exc:
        if claimed and not reserved and not exc.reconciliation_required:

            def rejected(run: Any, metadata: dict[str, Any]) -> None:
                call = metadata["model_requests"][request_id]
                if call["state"] == "reserved":
                    run.metadata["reserved_cost_units"] = max(
                        0,
                        int(run.metadata.get("reserved_cost_units") or 0) - call["reserved_units"],
                    )
                    call.update(state="failed", error_code="insufficient_balance", cost_units=0)

            await anyio.to_thread.run_sync(lambda: store.update(binding.run_id, rejected))
            finished = True
            raise HTTPException(402, "Model wallet balance is insufficient") from exc
        raise HTTPException(409, "Model admission or settlement requires reconciliation") from exc
    except XiaoxBindingError as exc:
        raise HTTPException(409, "Model admission or settlement requires reconciliation") from exc
    except _ModelSettlementStorageError as exc:
        await record_failure(exc, stream_phase="settlement")
        raise HTTPException(503, "Model settlement requires reconciliation") from exc
    except (ModelCircuitOpenError, ModelConcurrencyLimitError, ModelRateLimitError) as exc:
        raise HTTPException(
            429, "Model request admission was denied", headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    except httpx.HTTPError as exc:
        slot_failure = exc
        raise HTTPException(502, "Qualified model gateway is unavailable") from exc
    except ModelRequestTimeout as exc:
        slot_failure = exc
        if claimed:
            await record_failure(exc)
        raise HTTPException(504, "Model request deadline was exceeded") from exc
    except TimeoutError as exc:
        slot_failure = exc
        if claimed:
            await record_failure(exc)
        raise HTTPException(504, "Task model deadline was exceeded") from exc
    except ValueError as exc:
        slot_failure = exc
        if claimed:
            await record_failure(exc)
        raise HTTPException(502, "Qualified model gateway returned an invalid response") from exc
    finally:
        if not streaming_handoff:
            settle = None
            if claimed and not finished:
                if reserved and not network_started:
                    settle = lambda: finish_usage(
                        store,
                        binding.run_id,
                        request_id,
                        usage=_ZERO_USAGE,
                        usage_key=usage_key,
                        state="failed",
                    )
                else:
                    # A reservation failure can itself be an uncertain remote wallet operation.
                    settle = mark_unknown
            await close_resources(slot_failure, settle)
