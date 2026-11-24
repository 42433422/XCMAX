"""Account-bound Responses forwarding through the pinned OpenAI SDK.

The existing encrypted route token, request journal, pricing and Java wallet own
authorization and settlement. The SDK owns the native Responses wire protocol;
an uncertain attempt remains in the journal and can never execute again.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import APIError
from openai.types.responses.response_create_params import ResponseCreateParamsBase
from sqlalchemy.orm import Session

from modstore_server import llm_client_requests as ledger
from modstore_server.llm_billed_chat import _chat_total_deadline_s
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    enforce_risk_limits,
    estimate_preauthorization,
    rate_usage,
)
from modstore_server.llm_billing_recovery import complete_receipt, recover_receipt
from modstore_server.llm_billing_values import exact_reported_usage
from modstore_server.llm_gateway_contract import (
    StreamReceiptBudget,
    codex_route_contract,
    gateway_body,
)
from modstore_server.llm_key_resolver import read_chat_route_token
from modstore_server.llm_model_concurrency import (
    concurrency_key,
    controller as concurrency,
    is_throttled,
    retry_after_seconds,
)
from modstore_server.llm_model_gates import assert_llm_chat_allowed
from modstore_server.llm_responses_transport import ResponsesTransport, validate_responses_route
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.platform_model_transport import redact_key

MAX_REQUEST_BYTES = 4_194_304
_MAX_RECEIPT_BYTES = 16_777_216
_CONCURRENCY_WAIT_S = 8.0
_TERMINALS = {"response.completed", "response.incomplete", "response.failed"}
_ERRORS: tuple[type[Exception], ...] = (HTTPException, APIError, *RECOVERABLE_ERRORS)


def _error(code: str, message: str, *, status: int = 409, **detail: Any) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, **detail})


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _function_tools(tools: Any) -> bool:
    return isinstance(tools, list) and all(
        isinstance(tool, dict)
        and (
            tool.get("type") == "function"
            or (
                tool.get("type") == "namespace"
                and isinstance(tool.get("tools"), list)
                and all(
                    isinstance(child, dict) and child.get("type") == "function"
                    for child in tool["tools"]
                )
            )
        )
        for tool in tools
    )


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(
        payload, dict
    ) or payload.keys() - ResponseCreateParamsBase.__annotations__.keys() - {"stream"}:
        raise _error(
            "CODEX_REQUEST_INVALID", "请求含不支持的 Responses 字段或路由控制。", status=400
        )
    if not isinstance(payload.get("model"), str) or "/" not in payload["model"]:
        raise _error("CODEX_REQUEST_INVALID", "model 必须与选定的供应商/模型一致。", status=400)
    if type(payload.get("stream", False)) is not bool or not payload.get("input"):
        raise _error("CODEX_REQUEST_INVALID", "Responses 需要显式输入和有效流式选项。", status=400)
    if any(
        payload.get(key) for key in ("background", "conversation", "previous_response_id", "prompt")
    ) or payload.get("store") not in (None, False):
        raise _error(
            "CODEX_REQUEST_INVALID",
            "当前运行时只支持显式上下文，不支持远端保存或后台执行。",
            status=400,
        )
    if payload.get("service_tier") not in (None, "default") or payload.get("truncation") not in (
        None,
        "disabled",
    ):
        raise _error(
            "CODEX_REQUEST_INVALID", "当前运行时使用默认服务级别和显式上下文。", status=400
        )
    if not _function_tools(payload.get("tools", [])):
        raise _error("CODEX_REQUEST_INVALID", "当前运行时仅支持由本机执行的函数工具。", status=400)
    source = payload["input"]
    if not isinstance(source, (str, list)) or (
        isinstance(source, list)
        and any(
            not isinstance(item, dict)
            or item.get("type", "message")
            not in {"message", "function_call", "function_call_output", "reasoning", "compaction"}
            for item in source
        )
    ):
        raise _error(
            "CODEX_REQUEST_INVALID", "Responses 需要完整消息和函数调用上下文。", status=400
        )
    return dict(payload)


def _identity(response: Any, expected: str, response_id: str | None = None) -> str:
    if (
        not isinstance(response, dict)
        or response.get("model") != expected
        or not isinstance(response.get("id"), str)
        or not response["id"]
        or (response_id is not None and response["id"] != response_id)
        or response.get("fallback_used")
        or response.get("_fallback_used")
    ):
        raise ValueError("response identity does not match the bound route")
    return str(response["id"])


def _replay(receipt: dict[str, Any]) -> JSONResponse | StreamingResponse:
    wire = receipt["wire"]
    headers = {**receipt["headers"], "X-XCMax-Request-Replayed": "true"}
    if wire.get("events") is not None:
        return StreamingResponse(
            iter(_sse(event) for event in wire["events"]),
            media_type="text/event-stream",
            headers=headers,
        )
    return JSONResponse(wire["response"], headers=headers)


async def run_billed_responses(
    request: Request, db: Session, user: User, payload: Any
) -> JSONResponse | StreamingResponse:
    body = _validate_payload(payload)
    key = request.headers.get("idempotency-key", "")
    if len(request.headers.getlist("idempotency-key")) != 1 or not ledger.KEY_PATTERN.fullmatch(
        key
    ):
        raise _error(
            "CODEX_REQUEST_KEY_REQUIRED",
            "每次原始模型请求需要独立且稳定的 Idempotency-Key。",
            status=422,
        )
    digest = ledger.request_digest({"operation": "responses", "payload": body})
    uid = int(user.id)
    state = ledger.existing_state(db, uid, key, digest)
    if state in {"completed", "settling"}:
        replay = ledger.completed_receipt(db, uid, key, digest)
        receipt = (
            replay[1]
            if replay and replay[0] == "replay"
            else await recover_receipt(
                db, uid, key, authorization_header(request), operation="responses", request=request
            )
        )
        if isinstance(receipt, dict) and receipt.get("operation") == "responses":
            return _replay(receipt)
    if state in {"conflict", "completed", "settling", "processing"}:
        raise _error(
            "CODEX_REQUEST_UNRESOLVED",
            "原请求正在处理或结算待核对，请保留原请求键查询，勿重新付费执行。",
            state=state,
        )
    token = request.headers.get("x-xcmax-route-token", "")
    if not token or len(request.headers.getlist("x-xcmax-route-token")) != 1:
        raise _error(
            "CODEX_ROUTE_EXPIRED", "缺少已绑定的模型配置，请重新读取当前运行时配置。", status=412
        )
    provider, model = body["model"].split("/", 1)
    try:
        route = read_chat_route_token(token, uid, provider, model)
        validate_responses_route(route)
    except HTTPException as exc:
        raise HTTPException(
            412 if exc.status_code == 409 else exc.status_code, exc.detail
        ) from None
    contract = route.runtime_contract or {}
    if not contract:
        raise _error(
            "CODEX_ROUTE_EXPIRED", "运行时模型配置快照已失效，请重新读取当前配置。", status=412
        )
    capabilities = contract.get("model_capabilities") or {}
    try:
        runtime = codex_route_contract(provider, model, capabilities)
    except HTTPException as exc:
        raise HTTPException(
            412 if exc.status_code == 409 else exc.status_code, exc.detail
        ) from None
    if contract.get("runtime") != runtime:
        raise _error(
            "CODEX_ROUTE_EXPIRED", "运行时模型配置快照已失效，请重新读取当前配置。", status=412
        )
    maximum = body.get("max_output_tokens", capabilities["max_output_tokens"])
    if type(maximum) is not int or not 0 < maximum <= capabilities["max_output_tokens"]:
        raise _error("CODEX_REQUEST_INVALID", "输出上限超过已确认的模型容量。", status=400)
    await assert_llm_chat_allowed(
        db, uid, provider, model, is_byok=route.key_source == "user_override"
    )
    messages = [{"role": "user", "content": json.dumps(body, ensure_ascii=False)}]
    enforce_risk_limits(db, uid, provider, model, messages, request)
    wallet = JavaWalletClient(request=request, verify_receipt=True)
    byok = route.key_source == "user_override"
    if not byok and not wallet.enabled:
        raise _error(
            "CODEX_BILLING_UNAVAILABLE",
            "平台模型钱包服务未就绪，请管理员检查现有计费服务。",
            status=503,
        )
    wallet.validate_pat(authorization_header(request))
    timeout = _chat_total_deadline_s()
    model_key = concurrency_key(provider, model)
    lease = await concurrency.acquire(db, model_key, wait_s=_CONCURRENCY_WAIT_S, timeout_s=timeout)
    if lease is None:
        # Saturated admission is a local decision: no journal row, no hold, no dispatch.
        raise HTTPException(
            429,
            {"code": "MODEL_CONCURRENCY_SATURATED", "message": "模型并发已满，请稍后重试。"},
            headers={"Retry-After": "1"},
        )
    slot_held = True

    def release_slot() -> None:
        nonlocal slot_held
        if slot_held:
            slot_held = False
            concurrency.release(db, lease)

    try:
        outcome, row = ledger.begin(db, uid, key, digest, timeout)
    except BaseException:
        release_slot()
        raise
    if outcome == "replay":
        release_slot()
        return _replay(row)
    if outcome != "run":
        release_slot()
        raise _error("CODEX_REQUEST_UNRESOLVED", "原请求已经受理，请保留原请求键。", state=outcome)
    request_id = ledger.attempt_request_id(uid, key, row.attempts)
    hold = WalletHold(f"byok-{request_id}", Decimal("0"), False)
    transport = None
    handed_off = False
    auth = authorization_header(request)

    async def close() -> None:
        if transport is not None:
            await transport.close()

    def unresolved() -> HTTPException:
        return _error(
            "CODEX_REQUEST_UNRESOLVED",
            "上游调用或结算状态待核对；原请求不会自动重跑。",
            state="settling",
            request_id=request_id,
            hold_no=hold.hold_no if hold.enabled or byok else "",
        )

    async def settle(
        result: dict[str, Any], headers: dict[str, str], events: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        assert transport is not None
        transport.verify(result, runtime["response_model"])
        _identity(result, runtime["response_model"])
        usage = exact_reported_usage(result.get("usage"))
        if (
            usage is None
            or result.get("status") not in {"completed", "incomplete", "failed"}
            or result.get("usage_estimated")
            or result["usage"].get("estimated")
        ):
            raise ValueError("response has no exact terminal usage")
        charge, pricing = (Decimal("0"), None) if byok else rate_usage(db, provider, model, usage)
        xcagi = {
            "schema": "xcmax.responses-billing.v1",
            **route.public_metadata(),
            "client_request_id": key,
            "request_id": request_id,
            "hold_no": hold.hold_no,
            "billed": not byok,
            "charge_amount": format(charge, ".2f"),
            "billing_status": "byok" if byok else "settled",
            "usage": result["usage"],
        }
        result["xcagi"] = xcagi
        receipt = {
            "operation": "responses",
            **route.public_metadata(),
            "client_request_id": key,
            "request_id": request_id,
            "hold_no": hold.hold_no,
            "billed": not byok,
            "charge_amount": xcagi["charge_amount"],
            "pricing": pricing,
            "usage": usage.__dict__,
            "response_status": result["status"],
            "headers": headers,
            "wire": {"response": result, "events": events},
        }
        ledger.prepare_settlement(db, row, receipt)
        if not byok:
            await wallet.settle(auth, hold, charge, request_id)
        completed = complete_receipt(db, row, receipt)
        concurrency.report_success(db, model_key)
        return completed

    try:
        # A crash after either wallet or model I/O must not get a new execution
        # lease. This also protects BYOK from an invisible duplicate vendor bill.
        ledger.mark_settling(db, row)
        if not byok:
            try:
                hold = await wallet.preauthorize(
                    auth,
                    estimate_preauthorization(db, provider, model, messages, maximum),
                    provider,
                    model,
                    request_id,
                )
            except HTTPException as exc:
                if exc.status_code in {400, 401, 402, 403, 422, 429}:
                    ledger.confirmed_no_charge(db, row)
                    ledger.finish(db, row, None)
                    raise
                raise unresolved() from None
        transport = ResponsesTransport(route, timeout)
        deadline = asyncio.get_running_loop().time() + timeout
        body.update(
            model=model,
            max_output_tokens=maximum,
            store=False,
            background=False,
            service_tier="default",
            truncation="disabled",
            extra_body=gateway_body(provider),
        )
        async with asyncio.timeout(timeout):
            await transport.open(body)
        source = transport.source
        headers = transport.headers
        if body.get("stream"):

            async def generate() -> AsyncIterator[str]:
                events: list[dict[str, Any]] = []
                terminal = None
                response_id = None
                size = 0
                stream_budget = StreamReceiptBudget()
                try:
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError("Responses deadline expired")
                        try:
                            async with asyncio.timeout(remaining):
                                event = await anext(source)
                        except StopAsyncIteration:
                            break
                        value = event.model_dump(mode="json", exclude_unset=True)
                        stream_budget.consume(value)
                        data = redact_key(
                            transport.project(value),
                            route.api_key,
                        )
                        size += len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                        if (
                            size > _MAX_RECEIPT_BYTES
                            or terminal is not None
                            or data.get("type") == "error"
                        ):
                            raise ValueError("Responses stream has no unique complete receipt")
                        result = data.get("response")
                        if isinstance(result, dict):
                            response_id = _identity(result, runtime["response_model"], response_id)
                        if response_id is None:
                            raise ValueError(
                                "Responses stream must establish its model identity first"
                            )
                        events.append(data)
                        if data.get("type") in _TERMINALS:
                            if not isinstance(result, dict) or data["type"] != "response." + str(
                                result.get("status")
                            ):
                                raise ValueError("invalid Responses terminal")
                            terminal = data
                        else:
                            yield _sse(data)
                    if terminal is None:
                        raise ValueError("Responses stream ended without terminal usage")
                    await close()
                    await settle(terminal["response"], headers, events)
                    yield _sse(terminal)
                except _ERRORS as exc:
                    db.rollback()
                    if is_throttled(exc):
                        concurrency.report_throttled(db, model_key, retry_after_seconds(exc))
                    yield _sse(
                        {
                            "type": "error",
                            "code": "CODEX_REQUEST_UNRESOLVED",
                            "message": "上游调用或结算状态待核对；原请求不会自动重跑。",
                            "request_id": request_id,
                        }
                    )
                finally:
                    await close()
                    release_slot()

            handed_off = True
            return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)
        result = redact_key(
            transport.project(source.model_dump(mode="json", exclude_unset=True)), route.api_key
        )
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > _MAX_RECEIPT_BYTES:
            raise ValueError("Responses result exceeds the receipt limit")
        await close()
        receipt = await settle(result, headers)
        return JSONResponse(receipt["wire"]["response"], headers=headers)
    except HTTPException:
        if row.state == "failed":
            raise
        db.rollback()
        raise unresolved() from None
    except _ERRORS as exc:
        db.rollback()
        if is_throttled(exc):
            concurrency.report_throttled(db, model_key, retry_after_seconds(exc))
        raise unresolved() from None
    finally:
        if not handed_off:
            await close()
            release_slot()
