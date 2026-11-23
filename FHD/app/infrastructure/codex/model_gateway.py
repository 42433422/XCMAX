"""Run-bound Responses forwarding through existing admission and billing.

This proxy does not translate Chat Completions or invent provider responses.
Only an explicitly qualified gateway is used; redirects, environment proxies,
native remote tools and client-supplied provider changes are rejected.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from httpx_sse import EventSource

from app.infrastructure.codex.policy import ModelRoute

router = APIRouter()
MODEL_PATH = "/api/agent-runtime/codex/responses"
_ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
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
    from app.infrastructure.codex.tool_names import CODEX_TOOL_NAMES

    if not isinstance(tools, list):
        raise HTTPException(400, "Invalid model tool list")
    for tool in tools:
        if not isinstance(tool, dict):
            raise HTTPException(400, "Invalid model tool")
        name = tool.get("name", "")
        # Codex can group MCP functions in a namespace. Only our bridge is valid.
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
            f"mcp__xcmax__{item}" for item in CODEX_TOOL_NAMES
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
    from app.infrastructure.codex.tool_names import CODEX_TOOL_NAMES

    if not isinstance(item, dict):
        raise ValueError("Invalid model output item")
    kind = item.get("type")
    if kind in {"message", "reasoning", "compaction"}:
        return
    name, namespace = item.get("name"), item.get("namespace")
    if kind == "function_call" and (
        namespace == "mcp__xcmax"
        and name in CODEX_TOOL_NAMES
        or namespace in {None, ""}
        and name in {f"mcp__xcmax__{tool}" for tool in CODEX_TOOL_NAMES}
    ):
        return
    raise ValueError("Model proposed a tool outside the controlled business bridge")


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


def _remaining(binding: Any) -> float:
    value = binding.metadata.get("deadline_at")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
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
) -> tuple[Any, int]:
    from app.application.agent_orchestrator.budget import budget_exceeded_payload
    from app.infrastructure.billing.model_usage import estimate_llm_cost_units
    from app.infrastructure.llm.model_admission import admit_model_call

    reserve = estimate_llm_cost_units(total_tokens=route.context_window)
    with store.scope(token, audience="model") as binding:
        _remaining(binding)
        config = binding.metadata.get("runtime_config") or {}
        if config.get("route_identity") != route.identity or config.get("model") != route.model:
            raise HTTPException(409, "The configured gateway no longer matches this task")
        admit_model_call(None, profile="codex", kwargs={"model": route.model})

        def claim(run: Any, metadata: dict[str, Any]) -> None:
            if metadata.get("model_reconciliation_required"):
                raise HTTPException(409, "Previous model usage requires reconciliation")
            calls = metadata.setdefault("model_requests", {})
            if any(item.get("state") in {"reserved", "unknown"} for item in calls.values()):
                raise HTTPException(409, "A model request is still in progress or unconfirmed")
            if len(calls) >= route.max_model_calls:
                raise HTTPException(429, "Task model-call limit reached")
            held = int(run.metadata.get("reserved_cost_units") or 0)
            if budget_exceeded_payload(
                run, additional_cost_units=held + reserve, scope="codex_model"
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
            }

        store.update(binding.run_id, claim, generation=binding.metadata.get("generation"))
        return binding, reserve


def _finish(
    store: Any,
    run_id: str,
    request_id: str,
    *,
    usage: dict[str, int] | None,
    usage_key: str,
    state: str = "completed",
    market_route: ModelRoute | None = None,
    platform_receipt: Any = None,
) -> None:
    from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
    from app.application.agent_orchestrator.run_models import LLMCall
    from app.infrastructure.billing.model_reservation import settle_model_usage

    settled: dict[str, Any] | None
    if market_route is not None and usage is not None:
        from app.infrastructure.billing.model_reservation import record_platform_model_usage

        binding = store.get(run_id)
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
        settled = settle_model_usage(usage_key, usage) if usage is not None else None

    def finish(run: Any, metadata: dict[str, Any]) -> None:
        call = metadata["model_requests"][request_id]
        if call.get("state") in {"completed", "failed"}:
            return
        call.update(state=state if settled else "unknown", usage_key=usage_key)
        if settled is None or usage is None:
            metadata["model_reconciliation_required"] = True
            return
        call.update(usage=usage, cost_units=settled["cost_units"])
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
                    "source": "codex.model_gateway",
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

    store.update(run_id, finish)


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
    from app.infrastructure.codex.binding import CodexBindingError
    from app.infrastructure.llm.model_admission import model_call_slot, model_rate_limit_scope
    from app.utils.operational_errors import BOUNDARY_ERRORS

    store = request.app.state.codex_binding_store
    route: ModelRoute = request.app.state.codex_model_route
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "A run-bound model token is required")
    token = auth[7:]
    try:
        binding = await anyio.to_thread.run_sync(
            lambda: store.authenticate(token, audience="model")
        )
    except CodexBindingError as exc:
        raise HTTPException(403, "Runtime model authorization is invalid") from exc
    if binding.run_id != getattr(request.app.state, "codex_run_id", None):
        raise HTTPException(403, "Runtime model authorization belongs to another task")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > route.max_request_bytes:
            raise HTTPException(413, "Model request is too large")
    try:
        body = _prepare_body(json.loads(raw), route)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid Responses request") from exc
    route.token()  # Validate the account credential without persisting it.
    request_group = "request_" + uuid.uuid4().hex
    request_id = "model_" + uuid.uuid4().hex
    usage_key = f"codex:{binding.run_id}:{request_id}"
    stack = ExitStack()
    client = None
    upstream = None
    claimed = False
    reserved = False
    network_started = False
    finished = False
    streaming_handoff = False
    slot_failure: BaseException | None = None
    platform_receipt: Any = None

    def finish_usage(*args: Any, **kwargs: Any) -> None:
        _finish(
            *args,
            **kwargs,
            market_route=route if route.gateway_kind == "market" else None,
            platform_receipt=platform_receipt,
        )

    def close_slot(error: BaseException | None = None) -> None:
        stack.__exit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )

    def mark_unknown() -> None:
        if claimed:
            finish_usage(store, binding.run_id, request_id, usage=None, usage_key=usage_key)

    try:
        with model_rate_limit_scope(binding.context):
            stack.enter_context(
                model_call_slot(SimpleNamespace(provider_id=route.provider_id), profile="codex")
            )
        from app.infrastructure.llm.retry_policy import (
            is_safe_transport_retry,
            model_failure_details,
        )

        async def record_failure(error: BaseException, *, output_started: bool = False) -> None:
            details = model_failure_details(
                error,
                stage="codex.responses",
                attempt=attempt,
                elapsed_ms=(time.monotonic() - attempt_started) * 1000,
                output_started=output_started,
            )
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                details.update(outcome="not_started", retryable=True)
            if isinstance(error, ModelGatewayContractError):
                details.update(failure_kind=error.code, failure_reason=str(error), retryable=False)

            def record(run: Any, metadata: dict[str, Any]) -> None:
                call = metadata.get("model_requests", {}).get(request_id)
                if call is not None:
                    call["diagnostic"] = details
                run.metadata["runtime_failure_kind"] = details["failure_kind"]
                run.metadata["runtime_failure_reason"] = details["failure_reason"]
                run.metadata["runtime_failure_stage"] = "model"
                run.add_event("runtime.model.failure", details["failure_reason"], details)

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
            usage_key = f"codex:{binding.run_id}:{request_id}"
            claimed = reserved = network_started = finished = False
            platform_receipt = None
            binding = await anyio.to_thread.run_sync(
                lambda: store.authenticate(token, audience="model")
            )
            remaining = _remaining(binding)
            await anyio.to_thread.run_sync(
                lambda: _claim(
                    store, token, route, request_id, request_group=request_group, attempt=attempt
                )
            )
            claimed = True
            if route.gateway_kind != "market":
                await anyio.to_thread.run_sync(
                    lambda: reserve_model_usage(
                        usage_key=usage_key,
                        run_id=binding.run_id,
                        user_id=binding.run.user_id,
                        provider_id=route.provider_id,
                        model=route.model,
                        token_ceiling=route.context_window,
                    )
                )
            # The platform reserves and settles its wallet. _claim still checks
            # the original task's accumulated budget and model-call ceiling.
            reserved = True
            await anyio.to_thread.run_sync(lambda: store.authenticate(token, audience="model"))
            client_factory = getattr(request.app.state, "codex_http_client_factory", None)
            client_options: dict[str, Any] = {
                "timeout": httpx.Timeout(min(60.0, remaining), connect=min(15.0, remaining)),
                "trust_env": False,
                "follow_redirects": False,
            }
            if client_factory is None:
                from app.infrastructure.codex.qualification import IndependentModelTransport

                client_options["transport"] = IndependentModelTransport(route)
                client_factory = httpx.AsyncClient
            client = client_factory(**client_options)
            headers = {"Accept": "text/event-stream" if body.get("stream") else "application/json"}
            headers.update(route.headers(request_id))
            outbound = client.build_request(
                "POST",
                route.base_url + "/responses",
                headers=headers,
                json=body,
            )
            network_started = True
            try:
                with anyio.fail_after(min(60.0, _remaining(binding))):
                    upstream = await client.send(outbound, stream=True)
            except httpx.HTTPError as exc:
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
                await client.aclose()
                client = None
                delay = 0.25 * 2 ** (attempt - 1)
                if _remaining(binding) <= delay:
                    raise HTTPException(
                        408, "Task deadline cannot admit another model attempt"
                    ) from exc
                await anyio.sleep(delay)
                continue
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
            await record_failure(slot_failure)
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
            if upstream.status_code == 429 and attempt < 3:
                try:
                    delay = max(0.25, min(float(upstream.headers.get("retry-after", "0.5")), 5.0))
                except ValueError:
                    delay = 0.5
                if _remaining(binding) > delay:
                    await upstream.aclose()
                    await client.aclose()
                    upstream = client = None
                    slot_failure = None
                    await anyio.sleep(delay)
                    continue
            return JSONResponse(
                {
                    "error": {
                        "message": "Qualified model gateway request failed",
                        "type": "upstream_error",
                    }
                },
                status_code=upstream.status_code if definite else 502,
            )
        assert upstream is not None and client is not None
        slot_failure = None
        if not body.get("stream"):
            with anyio.fail_after(_remaining(binding)):
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
                await record_failure(error)
                if any(item.get("type") == "function_call" for item in response.get("output", [])):
                    raise error
            return JSONResponse(response)

        async def events():
            completed = False
            terminal = False
            failure = None
            identity_verified = False
            output_visible = False
            held: list[bytes] = []
            held_bytes = 0
            hold_tools = False
            try:
                with anyio.fail_after(_remaining(binding)):
                    async for event in EventSource(upstream).aiter_sse():
                        if event.data == "[DONE]":
                            continue
                        payload = json.loads(event.data)
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid model event")
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
                            _validate_output_item(payload.get("item"))
                            if (payload.get("item") or {}).get("type") == "function_call":
                                hold_tools = True
                        if str(kind).startswith("response.function_call_arguments."):
                            hold_tools = True
                        if kind in {f"response.{status}" for status in _TERMINAL_STATES}:
                            response = payload.get("response") or {}
                            _validate_model_output(response)
                            status = response.get("status")
                            if kind != f"response.{status}":
                                raise ModelGatewayContractError(
                                    "model_terminal_state_invalid",
                                    "Gateway terminal event does not match its response state",
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
                                await record_failure(error, output_started=output_visible)
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
                await record_failure(exc, output_started=output_visible)
                error = {
                    "code": getattr(exc, "code", "model_stream_error"),
                    "message": (
                        "Model stream output was rejected"
                        if terminal
                        else "Model stream requires reconciliation"
                    ),
                }
                yield f"data: {json.dumps({'type': 'error', 'error': error})}\n\n".encode()
            finally:
                with anyio.CancelScope(shield=True):
                    if not terminal:
                        await anyio.to_thread.run_sync(mark_unknown)
                    await upstream.aclose()
                    await client.aclose()
                    close_slot(failure)

        finished = True  # Streaming iterator now owns cleanup and settlement.
        streaming_handoff = True
        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
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
    except CodexBindingError as exc:
        raise HTTPException(409, "Model admission or settlement requires reconciliation") from exc
    except (ModelCircuitOpenError, ModelConcurrencyLimitError, ModelRateLimitError) as exc:
        raise HTTPException(
            429, "Model request admission was denied", headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    except httpx.HTTPError as exc:
        slot_failure = exc
        raise HTTPException(502, "Qualified model gateway is unavailable") from exc
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
            if claimed and not finished:
                if reserved and not network_started:
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
                else:
                    # A reservation failure can itself be an uncertain remote wallet operation.
                    await anyio.to_thread.run_sync(mark_unknown)
            if upstream is not None:
                await upstream.aclose()
            if client is not None:
                await client.aclose()
            close_slot(slot_failure)
