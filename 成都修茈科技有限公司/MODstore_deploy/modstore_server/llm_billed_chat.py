"""计费 LLM 对话与流式换模（从 llm_api 抽出，避免巨文件棘轮增长）。"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

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
from modstore_server.llm_chat_proxy import chat_dispatch, chat_dispatch_stream
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.models import User
from modstore_server.multimodal_llm import (
    messages_use_openai_multipart_content,
    validate_multimodal_payload_size,
)

logger = logging.getLogger(__name__)


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_billed_llm_chat_once(
    request: Request,
    db: Session,
    user: User,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    conversation_id: Optional[int] = None,
) -> dict[str, Any]:
    """单次计费对话（无 failover）。"""
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    api_key, key_source = resolve_api_key(db, user.id, provider)
    if not api_key:
        raise HTTPException(
            400,
            f"供应商「{provider}」未配置可用 API Key（平台环境变量或 BYOK）。"
            f"请在钱包页为该厂商保存密钥，或将默认模型切换到已有密钥的厂商；"
            f"仅配置了其它厂商（如 DeepSeek）时，请把 LLM 默认供应商改为该厂商或切到「自选」。",
        )
    is_byok = key_source == "user_override"
    base = (
        resolve_base_url(db, user.id, provider)
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    msgs = messages
    if not msgs:
        raise HTTPException(400, "messages 不能为空")
    size_err = validate_multimodal_payload_size(msgs)
    if size_err:
        raise HTTPException(400, size_err)
    if (
        messages_use_openai_multipart_content(msgs)
        and provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    ):
        raise HTTPException(
            400,
            "多模态消息仅支持 OpenAI 兼容供应商（含 SiliconFlow、DashScope 等 chat/completions 网关）；"
            "请更换 provider 或改发纯文本。",
        )
    model = model.strip()
    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, msgs, request)
    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, provider, model, msgs, max_tokens)
        hold = await wallet.preauthorize(
            authorization_header(request), preauth_amount, provider, model, request_id
        )
    charge = Decimal("0")
    try:
        result = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            messages=msgs,
            max_tokens=max_tokens,
        )
        if not result.get("ok"):
            err = result.get("error") or "upstream error"
            status = result.get("status")
            try:
                status_code = int(status) if status is not None else None
            except (TypeError, ValueError):
                status_code = None
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(err),
                hold_no=hold.hold_no,
            )
            raise HTTPException(status_code or 502, str(err))
        content = result.get("content", "")
        usage = usage_from_response(result.get("usage") or {}, msgs, content)
        if is_byok:
            charge = Decimal("0")
        else:
            charge = calculate_charge(db, provider, model, usage)
            await wallet.settle(authorization_header(request), hold, charge, request_id)
        conversation_row_id = save_success_log(
            db,
            user_id=user.id,
            provider=provider,
            model=model,
            messages=msgs,
            content=content,
            usage=usage,
            charge=charge,
            hold_no=hold.hold_no,
            conversation_id=conversation_id,
        )
    except HTTPException as exc:
        try:
            await wallet.release(authorization_header(request), hold, str(exc.detail), request_id)
        except Exception:
            logger.exception("failed to release LLM wallet hold")
        raise
    except Exception as exc:
        try:
            save_failure_log(
                db,
                user_id=user.id,
                provider=provider,
                model=model,
                error=str(exc),
                hold_no=hold.hold_no,
            )
            await wallet.release(authorization_header(request), hold, str(exc), request_id)
        except Exception:
            logger.exception("failed to release LLM wallet hold after unexpected error")
        raise
    return {
        "ok": True,
        "content": content,
        "conversation_id": conversation_row_id,
        "usage": usage.__dict__,
        "charge_amount": float(charge),
        "hold_no": hold.hold_no,
        "key_source": key_source,
        "billed": not is_byok,
        "provider": provider,
        "model": model,
        "request_id": request_id,
    }


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
) -> dict[str, Any]:
    """执行一轮 LLM 对话并完成钱包预授权/结算；配额/限流时可自动切换备用模型。"""
    primary_provider = (provider or "").strip().lower()
    primary_model = (model or "").strip()
    if allow_failover:
        candidates = await list_chat_failover_candidates(
            db, int(user.id), primary_provider, primary_model
        )
    else:
        candidates = [(primary_provider, primary_model)]
    if not candidates:
        candidates = [(primary_provider, primary_model)]

    key_source_by_provider: dict[str, str] = {}
    for p, _m in candidates:
        _key, src = resolve_api_key(db, user.id, p)
        if _key:
            key_source_by_provider[p] = src

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
            return out
        except HTTPException as exc:
            last_exc = exc
            detail = str(exc.detail)
            rest = remaining_candidates_after_failure(
                queue,
                idx,
                error_text=detail,
                status_code=exc.status_code,
                key_source_by_provider=key_source_by_provider,
            )
            if not rest:
                raise
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
    raise HTTPException(502, "LLM 调用失败且无可用备用模型")


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
) -> StreamingResponse:
    primary_provider = (provider or "").strip().lower()
    primary_model = (model or "").strip()
    msgs = messages
    if not msgs:
        raise HTTPException(400, "messages 不能为空")
    size_err = validate_multimodal_payload_size(msgs)
    if size_err:
        raise HTTPException(400, size_err)

    if bool(allow_failover):
        candidates = await list_chat_failover_candidates(
            db, int(user.id), primary_provider, primary_model
        )
    else:
        candidates = [(primary_provider, primary_model)]
    if not candidates:
        candidates = [(primary_provider, primary_model)]

    key_source_by_provider: dict[str, str] = {}
    for p, _m in candidates:
        k, src = resolve_api_key(db, user.id, p)
        if k:
            key_source_by_provider[p] = src

    if primary_provider not in key_source_by_provider and primary_provider in KNOWN_PROVIDERS:
        raise HTTPException(
            400,
            f"供应商「{primary_provider}」未配置可用 API Key（平台环境变量或 BYOK）。",
        )

    async def gen():
        queue = list(candidates)
        attempted: list[str] = []
        idx = 0
        last_error = "LLM 流式调用失败且无可用备用模型"
        while idx < len(queue):
            prov, mdl = queue[idx]
            attempted.append(f"{prov}/{mdl}")
            api_key, key_source = resolve_api_key(db, user.id, prov)
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
                    yield _sse("error", {"ok": False, "error": last_error})
                    return
                queue = queue[: idx + 1] + rest
                idx += 1
                continue

            is_byok = key_source == "user_override"
            base = (
                resolve_base_url(db, user.id, prov)
                if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                else None
            )
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
                    yield _sse("error", {"ok": False, "error": last_error, "status": exc.status_code})
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
                    preauth_amount = estimate_preauthorization(
                        db, prov, mdl, msgs, max_tokens
                    )
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
                    yield _sse("error", {"ok": False, "error": last_error, "status": exc.status_code})
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
                "key_source": key_source,
                "billed": not is_byok,
                "provider": prov,
                "model": mdl,
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
                                authorization_header(request), hold, str(err), request_id
                            )
                        except Exception:
                            logger.exception(
                                "failed to release LLM wallet hold after stream upstream error"
                            )
                        last_error = str(err)
                        if (
                            not emitted_delta
                            and is_chat_failoverable_failure(last_error, status_code)
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
                        yield _sse(
                            "error",
                            {"ok": False, "error": last_error, "status": status},
                        )
                        return
                    if ev.get("type") == "usage":
                        upstream_usage = ev.get("usage") or {}
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
                        await wallet.settle(
                            authorization_header(request), hold, charge, request_id
                        )
                    conversation_id = save_success_log(
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
                        "conversation_id": conversation_id,
                        "usage": usage.__dict__,
                        "charge_amount": float(charge),
                        "hold_no": hold.hold_no,
                        "key_source": key_source,
                        "billed": not is_byok,
                        "provider": prov,
                        "model": mdl,
                    }
                    if len(attempted) > 1:
                        done["failover_from"] = f"{primary_provider}/{primary_model}"
                        done["failover_attempts"] = list(attempted)
                    yield _sse("done", done)
                    return
                # break from async for → try next candidate
                continue
            except Exception as exc:
                try:
                    save_failure_log(
                        db,
                        user_id=user.id,
                        provider=prov,
                        model=mdl,
                        error=str(exc),
                        hold_no=hold.hold_no,
                    )
                    await wallet.release(
                        authorization_header(request), hold, str(exc), request_id
                    )
                except Exception:
                    logger.exception(
                        "failed to release LLM wallet hold after unexpected stream error"
                    )
                last_error = str(exc)
                if not emitted_delta and is_chat_failoverable_failure(last_error, None):
                    rest = remaining_candidates_after_failure(
                        queue,
                        idx,
                        error_text=last_error,
                        status_code=None,
                        key_source_by_provider=key_source_by_provider,
                    )
                    if rest:
                        queue = queue[: idx + 1] + rest
                        idx += 1
                        continue
                yield _sse("error", {"ok": False, "error": last_error})
                return
        yield _sse("error", {"ok": False, "error": last_error})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

