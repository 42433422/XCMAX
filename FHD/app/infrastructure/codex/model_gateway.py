"""Run-bound Responses forwarding through existing admission and billing.

This proxy does not translate Chat Completions or invent provider responses.
Only an explicitly qualified gateway is used; redirects, environment proxies,
native remote tools and client-supplied provider changes are rejected.
"""

from __future__ import annotations

import json
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
    from app.infrastructure.codex.tools import CODEX_TOOL_NAMES

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
    from app.infrastructure.codex.tools import CODEX_TOOL_NAMES

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
    if not isinstance(body, dict) or body.get("model", route.model) != route.model:
        raise HTTPException(409, "The model route is pinned to this task")
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
    }


def _claim(store: Any, token: str, route: ModelRoute, request_id: str) -> tuple[Any, int]:
    from app.application.agent_orchestrator.budget import budget_exceeded_payload
    from app.infrastructure.billing.model_usage import estimate_llm_cost_units
    from app.infrastructure.llm.model_admission import admit_model_call

    reserve = estimate_llm_cost_units(total_tokens=route.context_window)
    with store.scope(token, audience="model") as binding:
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
                "provider_id": route.provider_id,
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
) -> None:
    from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
    from app.application.agent_orchestrator.run_models import LLMCall
    from app.infrastructure.billing.model_reservation import settle_model_usage

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
        run.metadata["reserved_cost_units"] = max(
            0,
            int(run.metadata.get("reserved_cost_units") or 0) - call["reserved_units"],
        )
        run.llm_calls.append(
            LLMCall(
                call_id=request_id,
                provider_id=call["provider_id"],
                model=call["model"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                cost_units=settled["cost_units"],
                billing_status=settled.get("billing_status", ""),
                status="completed" if state == "completed" else "failed",
                metadata={"usage_key": usage_key, "source": "codex.model_gateway"},
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
    upstream_key = route.token()
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

    def close_slot(error: BaseException | None = None) -> None:
        stack.__exit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )

    def mark_unknown() -> None:
        if claimed:
            _finish(store, binding.run_id, request_id, usage=None, usage_key=usage_key)

    try:
        with model_rate_limit_scope(binding.context):
            stack.enter_context(
                model_call_slot(SimpleNamespace(provider_id=route.provider_id), profile="codex")
            )
        await anyio.to_thread.run_sync(lambda: _claim(store, token, route, request_id))
        claimed = True
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
        reserved = True
        await anyio.to_thread.run_sync(lambda: store.authenticate(token, audience="model"))
        client_factory = getattr(request.app.state, "codex_http_client_factory", httpx.AsyncClient)
        client = client_factory(
            timeout=httpx.Timeout(120, connect=15), trust_env=False, follow_redirects=False
        )
        headers = {"Accept": "text/event-stream" if body.get("stream") else "application/json"}
        if upstream_key:
            headers["Authorization"] = f"Bearer {upstream_key}"
        outbound = client.build_request(
            "POST",
            route.base_url + "/responses",
            headers=headers,
            json=body,
        )
        network_started = True
        upstream = await client.send(outbound, stream=True)
        if upstream.status_code >= 300:
            slot_failure = httpx.HTTPStatusError(
                "Qualified gateway rejected request", request=outbound, response=upstream
            )
            # Error bodies can contain credentials/echoed prompts. Do not relay them.
            definite = 400 <= upstream.status_code < 500 and upstream.status_code != 408
            await anyio.to_thread.run_sync(
                lambda: _finish(
                    store,
                    binding.run_id,
                    request_id,
                    usage=_ZERO_USAGE if definite else None,
                    usage_key=usage_key,
                    state="failed",
                )
            )
            finished = True
            return JSONResponse(
                {
                    "error": {
                        "message": "Qualified model gateway request failed",
                        "type": "upstream_error",
                    }
                },
                status_code=upstream.status_code if definite else 502,
            )
        if not body.get("stream"):
            response = json.loads(await upstream.aread())
            _validate_model_output(response)
            usage = response_usage(response)
            await anyio.to_thread.run_sync(
                lambda: _finish(
                    store,
                    binding.run_id,
                    request_id,
                    usage=usage,
                    usage_key=usage_key,
                )
            )
            finished = True
            if usage is None:
                raise HTTPException(502, "Gateway response omitted verified usage")
            return JSONResponse(response)

        async def events():
            completed = False
            failure = None
            try:
                async for event in EventSource(upstream).aiter_sse():
                    if event.data == "[DONE]":
                        continue
                    payload = json.loads(event.data)
                    if not isinstance(payload, dict):
                        raise ValueError("Invalid model event")
                    kind = payload.get("type", event.event)
                    if kind in {"response.output_item.added", "response.output_item.done"}:
                        _validate_output_item(payload.get("item"))
                    if kind == "response.completed":
                        _validate_model_output(payload.get("response"))
                        usage = response_usage(payload.get("response") or {})
                        await anyio.to_thread.run_sync(
                            lambda: _finish(
                                store,
                                binding.run_id,
                                request_id,
                                usage=usage,
                                usage_key=usage_key,
                            )
                        )
                        if usage is None:
                            raise ModelReservationError("Gateway stream omitted verified usage")
                        completed = True
                    # Re-check token/session revocation before tool proposals become visible.
                    if kind in {"response.output_item.done", "response.completed"}:
                        await anyio.to_thread.run_sync(
                            lambda: store.authenticate(token, audience="model")
                        )
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
                    if completed:
                        break
                if not completed:
                    raise ModelReservationError("Gateway stream ended without completion")
            except BOUNDARY_ERRORS as exc:
                failure = exc
                yield b'data: {"type":"error","error":{"message":"Model stream requires reconciliation"}}\n\n'
            finally:
                with anyio.CancelScope(shield=True):
                    if not completed:
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
    except ValueError as exc:
        slot_failure = exc
        raise HTTPException(502, "Qualified model gateway returned an invalid response") from exc
    finally:
        if not streaming_handoff:
            if claimed and not finished:
                if reserved and not network_started:
                    await anyio.to_thread.run_sync(
                        lambda: _finish(
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
