# mypy: disable-error-code="call-overload"
"""OpenAI-compatible gateway for **XCauto** (修茈模型中转) and XCAGI desktop clients.

Uses a login JWT. A PAT with ``llm:use`` is accepted only when the dedicated
service-to-service wallet configuration is explicitly enabled on both services.
Billing / wallet preauthorize-settle mirrors ``POST /api/llm/chat``.

**Model parameter**

- ``xcauto-account`` (aliases: ``xcauto``, ``xcauto-default``, ``xiuci-account``,
  ``xiuci-default``, ``xiuci``): resolve provider + model like
  ``GET /api/llm/resolve-chat-default``.
- ``<provider>/<model_id>`` e.g. ``deepseek/deepseek-chat``: explicit upstream route.

**Client configuration (OpenAI SDK compatible)**

- ``OPENAI_BASE_URL=https://<market-host>/v1``
- ``OPENAI_API_KEY=<login JWT or configured llm:use PAT>``

``stream=true`` is not implemented here; use ``POST /api/llm/chat/stream`` for SSE.

``GET /v1/models`` 返回完整目录（含 llm/vlm/image/video/…），不只是计价表里的 LLM；
每条带 ``category`` / ``pricing`` / ``runtime_selectable``，便于桌面端选型与计费对齐。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.auth_service import PAT_PREFIX, resolve_pat_identity
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_api import resolve_default_llm_route, run_billed_llm_chat
from modstore_server.llm_billing import merge_catalog_pricing
from modstore_server.llm_catalog import get_models_for_provider
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS
from modstore_server.llm_model_gates import merge_catalog_capabilities
from modstore_server.llm_model_taxonomy import CATEGORY_ORDER, category_labels_zh
from modstore_server.models import User
from modstore_server.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai-gateway", "xcauto"])


def _get_llm_gateway_user(request: Request, authorization: Optional[str] = Header(None)) -> User:
    """PAT access is limited to the model gateway and requires explicit configuration."""
    raw = (authorization or "").strip()
    token = raw[7:].strip() if raw.startswith("Bearer ") else ""
    if token.startswith(PAT_PREFIX):
        if os.environ.get("MODSTORE_LLM_PAT_ENABLED") != "1":
            return _get_current_user(authorization, request)
        if (
            os.environ.get("PAYMENT_BACKEND", "python").strip().lower() != "java"
            or not os.environ.get("MODSTORE_LLM_WALLET_SIGNING_KEY_PATH")
            or not os.environ.get("MODSTORE_LLM_WALLET_KEY_ID")
            or not os.environ.get("MODSTORE_LLM_WALLET_MAX_CENTS", "").isdigit()
            or int(os.environ["MODSTORE_LLM_WALLET_MAX_CENTS"]) <= 0
        ):
            raise HTTPException(503, "模型密钥计费服务未配置")
        try:
            from modstore_server.llm_wallet_assertion import load_signing_key

            load_signing_key(os.environ["MODSTORE_LLM_WALLET_SIGNING_KEY_PATH"])
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(503, "模型密钥计费服务未配置") from exc
        identity = resolve_pat_identity(token)
        if not identity or str(identity.user.account_state or "").strip().lower() in {
            "deleted",
            "disabled",
            "suspended",
            "blocked",
        }:
            raise HTTPException(401, "凭证无效或已过期")
        if "llm:use" not in identity.scopes:
            raise HTTPException(403, "凭证权限不足")
        request.state.llm_pat_user_id = int(identity.user.id)
        return identity.user
    return _get_current_user(authorization, request)


# 账户路由虚拟名（XCauto 对外主品牌 + 历史 xiuci 别名）
XCauto_VIRTUAL_MODELS = frozenset(
    {
        "xcauto-account",
        "xcauto-default",
        "xcauto",
        "xiuci-account",
        "xiuci-default",
        "xiuci",
    }
)

_CATEGORY_ENDPOINT: dict[str, str] = {
    "llm": "/v1/chat/completions",
    "vlm": "/v1/chat/completions",
    "image": "/api/llm/image",
    "video": "/api/llm/video",
    "audio": "/api/llm/catalog",
    "embedding": "/api/llm/catalog",
    "rerank": "/api/llm/catalog",
    "other": "/api/llm/catalog",
}


class OAIChatMessage(BaseModel):
    role: str
    content: str | List[Dict[str, Any]]


class OAIChatCompletionRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=256)
    messages: List[OAIChatMessage] = Field(..., min_length=1)
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    stream: bool = False


def _parse_requested_model(model_raw: str) -> tuple[str, str]:
    """Return ``(provider, model_id)``. Empty strings mean «use account default»."""
    m = (model_raw or "").strip()
    if not m:
        raise HTTPException(400, "model is required")
    low = m.lower()
    if low in XCauto_VIRTUAL_MODELS:
        return "", ""
    if "/" in m:
        prov, mid = m.split("/", 1)
        prov = prov.strip()
        mid = mid.strip()
        if prov not in KNOWN_PROVIDERS:
            raise HTTPException(400, f"unknown provider in model: {prov}")
        if not mid:
            raise HTTPException(400, "model id empty after provider/")
        return prov, mid
    raise HTTPException(
        400,
        "model 须为 XCauto 虚拟名（xcauto-account）或「供应商/模型id」（如 deepseek/deepseek-chat）。",
    )


def _oai_model_entry(
    model_id: str,
    owned_by: str,
    *,
    created: int = 1704067200,
    category: str = "llm",
    display_name: str = "",
    runtime_selectable: bool | None = None,
    pricing: dict[str, Any] | None = None,
    capabilities: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cat = str(category or "other").strip().lower() or "other"
    entry: Dict[str, Any] = {
        "id": model_id,
        "object": "model",
        "created": created,
        "owned_by": owned_by,
        # OpenAI 兼容扩展：完整模态 / 计费 / 可选路由
        "category": cat,
        "category_label": category_labels_zh().get(cat, cat),
        "display_name": display_name or model_id,
        "endpoint": _CATEGORY_ENDPOINT.get(cat, "/api/llm/catalog"),
        "chat_compatible": cat in {"llm", "vlm"},
    }
    if runtime_selectable is not None:
        entry["runtime_selectable"] = bool(runtime_selectable)
    if isinstance(pricing, dict) and pricing:
        entry["pricing"] = pricing
    if isinstance(capabilities, dict) and capabilities:
        entry["capabilities"] = capabilities
    return entry


async def _build_catalog_model_entries(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """从完整平台目录展开 ``provider/model``，保留 category / pricing / selectable。"""
    providers_out: List[Dict[str, Any]] = []
    for provider in KNOWN_PROVIDERS:
        try:
            block = await get_models_for_provider(db, user_id, provider, force_refresh=False)
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.exception("gateway /v1/models catalog fetch failed for %s", provider)
            block = {"models": [], "models_detailed": []}
        providers_out.append(
            {
                "provider": provider,
                "models": list(block.get("models") or []),
                "models_detailed": list(block.get("models_detailed") or []),
            }
        )
    try:
        merge_catalog_capabilities(db, providers_out)
    except BOUNDARY_ERRORS:  # noqa: BLE001
        logger.exception("merge_catalog_capabilities failed in /v1/models")
    try:
        merge_catalog_pricing(db, providers_out)
    except BOUNDARY_ERRORS:  # noqa: BLE001
        logger.exception("merge_catalog_pricing failed in /v1/models")

    data: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for block in providers_out:
        provider = str(block.get("provider") or "").strip()
        if not provider:
            continue
        detailed = block.get("models_detailed") or []
        if isinstance(detailed, list) and detailed:
            for row in detailed:
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("id") or "").strip()
                if not mid:
                    continue
                oid = f"{provider}/{mid}"
                if oid in seen:
                    continue
                seen.add(oid)
                data.append(
                    _oai_model_entry(
                        oid,
                        provider,
                        category=str(row.get("category") or "other"),
                        display_name=str(row.get("display_name") or mid),
                        runtime_selectable=bool(row.get("runtime_selectable")),
                        pricing=(
                            row.get("pricing") if isinstance(row.get("pricing"), dict) else None
                        ),
                        capabilities=(
                            row.get("capabilities")
                            if isinstance(row.get("capabilities"), dict)
                            else None
                        ),
                    )
                )
            continue
        for mid in block.get("models") or []:
            text = str(mid or "").strip()
            if not text:
                continue
            oid = f"{provider}/{text}"
            if oid in seen:
                continue
            seen.add(oid)
            data.append(_oai_model_entry(oid, provider, category="llm", display_name=text))
    # 稳定排序：按 category 序再按 id
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    data.sort(
        key=lambda r: (
            order.get(str(r.get("category") or "other"), 99),
            str(r.get("id")),
        )
    )
    return data


@router.get("/models")
async def openai_list_models(
    db: Session = Depends(get_db),
    user: User = Depends(_get_llm_gateway_user),
):
    """OpenAI-compatible model list for XCauto gateway clients.

    完整传递平台目录：llm / vlm / image / video / audio / embedding / rerank，
    附带 category、pricing、runtime_selectable，供桌面端选型与计费对齐。
    """
    data: List[Dict[str, Any]] = [
        _oai_model_entry(
            "xcauto-account",
            "xcauto",
            category="llm",
            display_name="XCauto 账户默认路由",
            runtime_selectable=True,
        ),
        _oai_model_entry(
            "xiuci-account",
            "xiuci",
            category="llm",
            display_name="修茈账户默认路由（别名）",
            runtime_selectable=True,
        ),
    ]
    try:
        catalog_rows = await _build_catalog_model_entries(db, int(user.id))
        data.extend(catalog_rows)
    except BOUNDARY_ERRORS:  # noqa: BLE001
        logger.exception("gateway /v1/models full catalog failed; returning virtual models only")
    return {
        "object": "list",
        "data": data,
        "category_labels": category_labels_zh(),
        "note": (
            "chat_compatible=true 的模型走 POST /v1/chat/completions；"
            "image/video 请分别走 /api/llm/image|/api/llm/video。"
        ),
    }


@router.post("/chat/completions")
async def openai_chat_completions(
    request: Request,
    body: OAIChatCompletionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_get_llm_gateway_user),
):
    if body.stream:
        raise HTTPException(
            501,
            "stream=true 暂未在本网关实现；请使用 stream=false 或调用 POST /api/llm/chat/stream",
        )
    prov, mid = _parse_requested_model(body.model)
    if not prov:
        resolved = await resolve_default_llm_route(db, int(user.id))
        prov = str(resolved["provider"])
        mid = str(resolved["model"])

    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    out = await run_billed_llm_chat(
        request,
        db,
        user,
        provider=prov,
        model=mid,
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=None,
    )
    usage = out.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    resp_model = f"{prov}/{mid}"
    billed = bool(out.get("billed"))
    charge = out.get("charge_amount") or 0
    request_id = str(out.get("request_id") or "")
    payload: Dict[str, Any] = {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": resp_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": out.get("content") or ""},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        # 完整计费 / 模型传递（不依赖客户端是否保留响应头）
        "xcagi": {
            "provider": prov,
            "model": mid,
            "resolved_model": resp_model,
            "request_id": request_id,
            "billed": billed,
            "charge_amount_cny": charge,
            "key_source": out.get("key_source"),
            "hold_no": out.get("hold_no"),
            "category": "llm",
        },
    }
    headers = {
        "X-Xiuci-Request-Id": request_id,
        "X-Xiuci-Provider": prov,
        "X-Xiuci-Resolved-Model": mid,
        "X-Xiuci-Billed": "1" if billed else "0",
        "X-Xiuci-Charge-CNY": str(charge),
    }
    return JSONResponse(content=payload, headers=headers)
