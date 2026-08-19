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
) -> dict[str, Any]:
    """Execute and settle a single provider/model chat attempt."""
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
    request_id = new_request_id()
    enforce_risk_limits(db, user.id, provider, model, messages, request)
    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, provider, model, messages, max_tokens)
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
