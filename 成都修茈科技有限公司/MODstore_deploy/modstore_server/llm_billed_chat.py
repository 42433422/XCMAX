# mypy: disable-error-code="arg-type"
"""计费 LLM 对话与流式换模（从 llm_api 抽出，避免巨文件棘轮增长）。"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from modstore_server.llm_billed_once import failed_chat_route_detail
from modstore_server.llm_billed_once import run_billed_llm_chat_once as _run_billed_llm_chat_once
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    calculate_charge,
    enforce_risk_limits,
    estimate_preauthorization,
    new_request_id,
    save_failure_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_chat_failover import (
    is_chat_failoverable_failure,
    list_chat_failover_candidates,
    remaining_candidates_after_failure,
)
from modstore_server.llm_chat_proxy import chat_dispatch_stream
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    ChatRouteSnapshot,
    chat_route_snapshot,
    resolve_chat_route_snapshot,
)
from modstore_server.llm_model_taxonomy import classify_model
from modstore_server.models import User
from modstore_server.multimodal_llm import (
    messages_use_openai_multipart_content,
    validate_multimodal_payload_size,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_CHAT_ERRORS = (HTTPException,) + RECOVERABLE_ERRORS


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _route_error(route: ChatRouteSnapshot, error: Any, status: int | None = None) -> str:
    return _sse(
        "error",
        {
            "ok": False,
            **failed_chat_route_detail(route, error),
            "status": status,
        },
    )


def _candidate_snapshots(
    db: Session,
    user_id: int,
    primary: ChatRouteSnapshot,
    candidates: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], dict[tuple[str, str], ChatRouteSnapshot]]:
    """An unusable backup must never block a healthy, already resolved primary."""
    pair = (primary.provider, primary.model)
    snapshots = {pair: primary}
    allowed = [pair]
    by_provider: dict[str, ChatRouteSnapshot | None] = {primary.provider: primary}
    for provider, model in candidates:
        pair = (provider, model)
        if pair in snapshots or classify_model(provider, model) not in {"llm", "vlm"}:
            continue
        if provider not in by_provider:
            try:
                by_provider[provider] = resolve_chat_route_snapshot(
                    db, user_id, provider, model, route_source="failover"
                )
            except HTTPException:
                by_provider[provider] = None
            except RECOVERABLE_ERRORS:
                by_provider[provider] = None
        route = by_provider[provider]
        if route is None or not route.api_key or route.key_source != primary.key_source:
            continue
        route = chat_route_snapshot(
            provider, model, route.api_key, route.base_url, route.key_source, "failover"
        )
        pair = (route.provider, route.model)
        if pair not in snapshots:
            snapshots[pair] = route
            allowed.append(pair)
    return allowed, snapshots


async def run_billed_llm_chat(
    request: Request,
    db: Session,
    user: User,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    conversation_id: Optional[int] = None,
    allow_failover: bool = True,
    route_snapshot: ChatRouteSnapshot | None = None,
) -> dict[str, Any]:
    """执行一轮 LLM 对话并完成钱包预授权/结算；配额/限流时可自动切换备用模型。"""
    primary = route_snapshot or resolve_chat_route_snapshot(db, user.id, provider, model)
    primary_provider, primary_model = primary.provider, primary.model
    if allow_failover and route_snapshot is None:
        candidates = await list_chat_failover_candidates(
            db, int(user.id), primary_provider, primary_model
        )
    else:
        candidates = [(primary_provider, primary_model)]
    if not candidates:
        candidates = [(primary_provider, primary_model)]

    candidates, snapshots = _candidate_snapshots(db, user.id, primary, candidates)
    key_source_by_provider = {p: snapshots[p, m].key_source for p, m in candidates}

    last_exc: Optional[HTTPException] = None
    queue = list(candidates)
    attempted: list[str] = []
    idx = 0
    while idx < len(queue):
        prov, mdl = queue[idx]
        attempted.append(f"{prov}/{mdl}")
        try:
            out = await _run_billed_llm_chat_once(
                request,
                db,
                user,
                provider=prov,
                model=mdl,
                messages=messages,
                max_tokens=max_tokens,
                conversation_id=conversation_id,
                route_snapshot=snapshots[prov, mdl],
            )
            if len(attempted) > 1:
                out["failover_from"] = f"{primary_provider}/{primary_model}"
                out["failover_attempts"] = attempted
                logger.info(
                    "llm chat failover ok primary=%s/%s used=%s/%s attempts=%s",
                    primary_provider,
                    primary_model,
                    prov,
                    mdl,
                    attempted,
                )
            out["route_state"] = "completed"
            return out
        except HTTPException as exc:
            last_exc = HTTPException(
                exc.status_code,
                failed_chat_route_detail(snapshots[prov, mdl], exc.detail),
                headers=exc.headers,
            )
            if (
                exc.status_code == 409
                and getattr(request.state, "llm_pat_user_id", None) is not None
                and isinstance(exc.detail, dict)
                and exc.detail.get("request_id")
            ):
                raise last_exc from exc
            detail = str(exc.detail)
            rest = remaining_candidates_after_failure(
                queue,
                idx,
                error_text=detail,
                status_code=exc.status_code,
                key_source_by_provider=key_source_by_provider,
            )
            if not rest:
                raise last_exc from exc
            logger.warning(
                "llm chat failover after %s/%s status=%s detail=%s next=%s",
                prov,
                mdl,
                exc.status_code,
                detail[:240],
                [f"{p}/{m}" for p, m in rest],
            )
            # 用裁剪后的剩余候选替换队列尾部
            queue = queue[: idx + 1] + rest
            idx += 1
            continue
    if last_exc is not None:
        raise last_exc
    raise HTTPException(502, failed_chat_route_detail(primary, "LLM 调用失败且无可用备用模型"))


async def stream_billed_llm_chat(
    request: Request,
    db: Session,
    user: User,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    conversation_id: Optional[int] = None,
    allow_failover: bool = True,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Any = None,
    route_snapshot: ChatRouteSnapshot | None = None,
) -> StreamingResponse:
    primary = route_snapshot or resolve_chat_route_snapshot(db, user.id, provider, model)
    primary_provider, primary_model = primary.provider, primary.model
    msgs = messages
    if not msgs:
        raise HTTPException(400, failed_chat_route_detail(primary, "messages 不能为空"))
    size_err = validate_multimodal_payload_size(msgs)
    if size_err:
        raise HTTPException(400, failed_chat_route_detail(primary, size_err))

    if allow_failover and route_snapshot is None:
        candidates = await list_chat_failover_candidates(
            db, int(user.id), primary_provider, primary_model
        )
    else:
        candidates = [(primary_provider, primary_model)]
    if not candidates:
        candidates = [(primary_provider, primary_model)]

    candidates, snapshots = _candidate_snapshots(db, user.id, primary, candidates)
    key_source_by_provider = {p: snapshots[p, m].key_source for p, m in candidates}

    if primary_provider not in key_source_by_provider and primary_provider in KNOWN_PROVIDERS:
        raise HTTPException(
            400,
            failed_chat_route_detail(
                primary, f"供应商「{primary_provider}」未配置可用 API Key（平台环境变量或 BYOK）。"
            ),
        )

    async def gen():
        queue = list(candidates)
        attempted: list[str] = []
        idx = 0
        last_error = "LLM 流式调用失败且无可用备用模型"
        route = primary
        while idx < len(queue):
            prov, mdl = queue[idx]
            attempted.append(f"{prov}/{mdl}")
            route = snapshots[prov, mdl]
            api_key, key_source = route.api_key, route.key_source
            if not api_key:
                idx += 1
                continue
            if (
                messages_use_openai_multipart_content(msgs)
                and prov not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            ):
                last_error = "多模态消息仅支持 OpenAI 兼容供应商；请更换 provider 或改发纯文本。"
                rest = remaining_candidates_after_failure(
                    queue,
                    idx,
                    error_text=last_error,
                    status_code=400,
                    key_source_by_provider=key_source_by_provider,
                )
                if not rest:
                    yield _route_error(route, last_error)
                    return
                queue = queue[: idx + 1] + rest
                idx += 1
                continue

            is_byok = key_source == "user_override"
            base = route.base_url if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS else None
            request_id = new_request_id()
            try:
                enforce_risk_limits(db, user.id, prov, mdl, msgs, request)
            except HTTPException as exc:
                last_error = str(exc.detail)
                rest = remaining_candidates_after_failure(
                    queue,
                    idx,
                    error_text=last_error,
                    status_code=exc.status_code,
                    key_source_by_provider=key_source_by_provider,
                )
                if not rest:
                    yield _route_error(route, exc.detail, exc.status_code)
                    return
                queue = queue[: idx + 1] + rest
                idx += 1
                continue

            wallet = JavaWalletClient()
            try:
                if is_byok:
                    hold = WalletHold(
                        hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False
                    )
                else:
                    preauth_amount = estimate_preauthorization(db, prov, mdl, msgs, max_tokens)
                    hold = await wallet.preauthorize(
                        authorization_header(request),
                        preauth_amount,
                        prov,
                        mdl,
                        request_id,
                    )
            except HTTPException as exc:
                last_error = str(exc.detail)
                rest = remaining_candidates_after_failure(
                    queue,
                    idx,
                    error_text=last_error,
                    status_code=exc.status_code,
                    key_source_by_provider=key_source_by_provider,
                )
                if not rest:
                    yield _route_error(route, exc.detail, exc.status_code)
                    return
                logger.warning(
                    "llm stream preauth failover after %s/%s: %s",
                    prov,
                    mdl,
                    last_error[:240],
                )
                queue = queue[: idx + 1] + rest
                idx += 1
                continue

            meta = {
                "ok": True,
                "request_id": request_id,
                "hold_no": hold.hold_no,
                **route.public_metadata(),
                "route_state": "selected",
                "billed": not is_byok,
            }
            if len(attempted) > 1:
                meta["failover_from"] = f"{primary_provider}/{primary_model}"
                meta["failover_attempts"] = list(attempted)
            yield _sse("meta", meta)

            parts: List[str] = []
            upstream_usage: Dict[str, Any] = {}
            emitted_delta = False
            try:
                async for ev in chat_dispatch_stream(
                    prov,
                    api_key=api_key,
                    base_url=base,
                    model=mdl,
                    messages=msgs,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice=tool_choice,
                ):
                    if ev.get("type") == "error":
                        err = ev.get("error") or "upstream error"
                        status = ev.get("status")
                        try:
                            status_code = int(status) if status is not None else None
                        except (TypeError, ValueError):
                            status_code = None
                        save_failure_log(
                            db,
                            user_id=user.id,
                            provider=prov,
                            model=mdl,
                            error=str(err),
                            hold_no=hold.hold_no,
                        )
                        try:
                            await wallet.release(
                                authorization_header(request),
                                hold,
                                str(err),
                                request_id,
                            )
                        except RECOVERABLE_ERRORS:
                            logger.exception(
                                "failed to release LLM wallet hold after stream upstream error"
                            )
                        last_error = str(err)
                        if not emitted_delta and is_chat_failoverable_failure(
                            last_error, status_code
                        ):
                            rest = remaining_candidates_after_failure(
                                queue,
                                idx,
                                error_text=last_error,
                                status_code=status_code,
                                key_source_by_provider=key_source_by_provider,
                            )
                            if rest:
                                logger.warning(
                                    "llm stream failover after %s/%s: %s next=%s",
                                    prov,
                                    mdl,
                                    last_error[:240],
                                    [f"{p}/{m}" for p, m in rest],
                                )
                                queue = queue[: idx + 1] + rest
                                idx += 1
                                break
                        yield _route_error(route, last_error, status_code)
                        return
                    if ev.get("type") == "usage":
                        upstream_usage = ev.get("usage") or {}
                        continue
                    if ev.get("type") == "toolcall":
                        choices = ev.get("choices") or []
                        if choices:
                            yield _sse("toolcall", {"choices": choices})
                        continue
                    if ev.get("type") == "delta":
                        delta = str(ev.get("delta") or "")
                        if delta:
                            emitted_delta = True
                            parts.append(delta)
                            yield _sse("delta", {"delta": delta})
                else:
                    # 正常结束（未因 failover break）
                    content = "".join(parts)
                    usage = usage_from_response(upstream_usage, msgs, content)
                    if is_byok:
                        charge = Decimal("0")
                    else:
                        charge = calculate_charge(db, prov, mdl, usage)
                        await wallet.settle(authorization_header(request), hold, charge, request_id)
                    saved_conversation_id = save_success_log(
                        db,
                        user_id=user.id,
                        provider=prov,
                        model=mdl,
                        messages=msgs,
                        content=content,
                        usage=usage,
                        charge=charge,
                        hold_no=hold.hold_no,
                        conversation_id=conversation_id,
                    )
                    done = {
                        "ok": True,
                        "content": content,
                        "conversation_id": saved_conversation_id,
                        "usage": usage.__dict__,
                        "charge_amount": float(charge),
                        "hold_no": hold.hold_no,
                        **route.public_metadata(),
                        "route_state": "completed",
                        "billed": not is_byok,
                    }
                    if len(attempted) > 1:
                        done["failover_from"] = f"{primary_provider}/{primary_model}"
                        done["failover_attempts"] = list(attempted)
                    yield _sse("done", done)
                    return
                # break from async for → try next candidate
                continue
            except _CHAT_ERRORS as exc:
                status_code = exc.status_code if isinstance(exc, HTTPException) else None
                last_error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                try:
                    save_failure_log(
                        db,
                        user_id=user.id,
                        provider=prov,
                        model=mdl,
                        error=str(exc),
                        hold_no=hold.hold_no,
                    )
                    await wallet.release(authorization_header(request), hold, str(exc), request_id)
                except RECOVERABLE_ERRORS:
                    logger.exception(
                        "failed to release LLM wallet hold after unexpected stream error"
                    )
                if not emitted_delta and is_chat_failoverable_failure(last_error, status_code):
                    rest = remaining_candidates_after_failure(
                        queue,
                        idx,
                        error_text=last_error,
                        status_code=status_code,
                        key_source_by_provider=key_source_by_provider,
                    )
                    if rest:
                        queue = queue[: idx + 1] + rest
                        idx += 1
                        continue
                yield _route_error(route, last_error, status_code)
                return
        yield _route_error(route, last_error)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
