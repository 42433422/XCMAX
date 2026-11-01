# mypy: disable-error-code="arg-type"
"""Single-provider billed LLM chat execution without failover."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, Request
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
from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    ChatRouteSnapshot,
    resolve_chat_route_snapshot,
)
from modstore_server.llm_model_gates import assert_llm_chat_allowed
from modstore_server.models import User
from modstore_server.multimodal_llm import (
    messages_use_openai_multipart_content,
    validate_multimodal_payload_size,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


async def run_billed_llm_chat_once(
    request: Request,
    db: Session,
    user: User,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    conversation_id: Optional[int] = None,
    route_snapshot: ChatRouteSnapshot | None = None,
) -> dict[str, Any]:
    """Execute one attempt and attach its actual route to every final receipt."""
    route = route_snapshot or resolve_chat_route_snapshot(db, user.id, provider, model)
    try:
        return await _execute_billed_chat(
            request, db, user, route, messages, max_tokens, conversation_id
        )
    except HTTPException as exc:
        raise HTTPException(
            exc.status_code, failed_chat_route_detail(route, exc.detail), headers=exc.headers
        ) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(502, failed_chat_route_detail(route, str(exc))) from exc


def failed_chat_route_detail(route: ChatRouteSnapshot, detail: Any) -> dict[str, Any]:
    """Keep existing error/reconciliation fields without serializing credentials."""
    fields = {"message", "error", "code", "recovery", "request_id", "hold_no", "status"}
    payload = (
        {key: value for key, value in detail.items() if key in fields}
        if isinstance(detail, dict)
        else {"message": str(detail)}
    )
    message = str(payload.get("message") or payload.get("error") or "模型调用失败")
    for name in ("message", "error"):
        value = str(payload.get(name) or message)
        for private in (route.api_key, route.base_url):
            if private:
                value = value.replace(private, "[REDACTED]")
        payload[name] = value
    return {**payload, **route.public_metadata(), "route_state": "failed"}


async def _execute_billed_chat(
    request: Request,
    db: Session,
    user: User,
    route: ChatRouteSnapshot,
    messages: list[dict[str, Any]],
    max_tokens: Optional[int],
    conversation_id: Optional[int],
) -> dict[str, Any]:
    provider, model = route.provider, route.model
    api_key, key_source = route.api_key, route.key_source
    is_byok = key_source == "user_override"
    base = route.base_url if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS else None
    if not messages:
        raise HTTPException(400, "messages 不能为空")
    size_error = validate_multimodal_payload_size(messages)
    if size_error:
        raise HTTPException(400, size_error)
    if (
        messages_use_openai_multipart_content(messages)
        and provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    ):
        raise HTTPException(
            400,
            "多模态消息仅支持 OpenAI 兼容供应商（含 SiliconFlow、DashScope 等 chat/completions 网关）；"
            "请更换 provider 或改发纯文本。",
        )
    model = model.strip()
    if getattr(request.state, "llm_pat_user_id", None) is not None:
        await assert_llm_chat_allowed(db, int(user.id), provider, model, is_byok=is_byok)
    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, messages, request)
    wallet = JavaWalletClient(request=request)
    if is_byok:
        if getattr(request.state, "llm_pat_user_id", None) is not None:
            wallet.validate_pat(authorization_header(request))
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, provider, model, messages, max_tokens)
        try:
            hold = await wallet.preauthorize(
                authorization_header(request), preauth_amount, provider, model, request_id
            )
        except HTTPException as exc:
            if getattr(request.state, "llm_pat_user_id", None) is not None and exc.status_code in {
                502,
                503,
                504,
            }:
                raise HTTPException(
                    409, {"message": "模型预授权状态待核对", "request_id": request_id}
                ) from exc
            raise
    charge = Decimal("0")
    upstream_started = False
    try:
        upstream_started = True
        result = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if not result.get("ok"):
            error = result.get("error") or "upstream error"
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
                error=str(error),
                hold_no=hold.hold_no,
            )
            raise HTTPException(status_code or 502, str(error))
        content = result.get("content", "")
        usage = usage_from_response(result.get("usage") or {}, messages, content)
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
            messages=messages,
            content=content,
            usage=usage,
            charge=charge,
            hold_no=hold.hold_no,
            conversation_id=conversation_id,
        )
    except HTTPException as exc:
        if upstream_started and getattr(request.state, "llm_pat_user_id", None) is not None:
            logger.error(
                "LLM settlement needs reconciliation request_id=%s hold=%s",
                request_id,
                hold.hold_no,
            )
            raise HTTPException(
                409,
                {
                    "message": "模型请求已发送，计费状态待核对",
                    "request_id": request_id,
                    "hold_no": hold.hold_no,
                },
            ) from exc
        try:
            await wallet.release(authorization_header(request), hold, str(exc.detail), request_id)
        except RECOVERABLE_ERRORS:
            logger.exception("failed to release LLM wallet hold")
        raise
    except RECOVERABLE_ERRORS as exc:
        if upstream_started and getattr(request.state, "llm_pat_user_id", None) is not None:
            logger.error(
                "LLM settlement needs reconciliation request_id=%s hold=%s",
                request_id,
                hold.hold_no,
            )
            raise HTTPException(
                409,
                {
                    "message": "模型请求已发送，计费状态待核对",
                    "request_id": request_id,
                    "hold_no": hold.hold_no,
                },
            ) from exc
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
        except RECOVERABLE_ERRORS:
            logger.exception("failed to release LLM wallet hold after unexpected error")
        raise
    return {
        "ok": True,
        "content": content,
        "conversation_id": conversation_row_id,
        "usage": usage.__dict__,
        "charge_amount": float(charge),
        "hold_no": hold.hold_no,
        **route.public_metadata(),
        "route_state": "completed",
        "billed": not is_byok,
        "request_id": request_id,
    }
