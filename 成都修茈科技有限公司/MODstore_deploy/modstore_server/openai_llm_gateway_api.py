"""OpenAI-compatible Chat Completions facade for XCAGI / desktop clients.

Uses the same auth as the rest of the market API (``Authorization: Bearer`` JWT or
developer PAT). Billing / wallet holds mirror ``POST /api/llm/chat``.

**Model parameter**

- ``xiuci-account`` (aliases: ``xiuci-default``, ``xiuci``): resolve provider + model
  exactly like ``GET /api/llm/resolve-chat-default`` (wallet default + keys).
- ``<provider>/<model_id>`` e.g. ``deepseek/deepseek-chat``: explicit route.

**Client configuration example**

- ``OPENAI_BASE_URL=https://<market-host>/v1``
- ``OPENAI_API_KEY=<JWT or PAT with llm:use>`` (PAT wallet settlement requires Java
  payment service to accept the same ``Authorization`` scheme as the browser session;
  if unsettled, use login JWT.)

``stream=true`` is not implemented here; use ``POST /api/llm/chat/stream`` for SSE.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_api import resolve_default_llm_route, run_billed_llm_chat
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS
from modstore_server.models import User

router = APIRouter(prefix="/v1", tags=["openai-gateway"])

XIUCI_VIRTUAL_MODELS = frozenset({"xiuci-account", "xiuci-default", "xiuci"})


class OAIChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]


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
    if low in XIUCI_VIRTUAL_MODELS:
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
        "model 须为账户路由虚拟名（xiuci-account）或「供应商/模型id」（如 deepseek/deepseek-chat）。",
    )


@router.post("/chat/completions")
async def openai_chat_completions(
    request: Request,
    body: OAIChatCompletionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
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
    }
    headers = {
        "X-Xiuci-Request-Id": str(out.get("request_id") or ""),
        "X-Xiuci-Provider": prov,
        "X-Xiuci-Resolved-Model": mid,
        "X-Xiuci-Billed": "1" if out.get("billed") else "0",
        "X-Xiuci-Charge-CNY": str(out.get("charge_amount") or 0),
    }
    return JSONResponse(content=payload, headers=headers)
