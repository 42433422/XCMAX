# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_api")


@_facade().router.get("/conversations/{conversation_id}")
async def llm_conversation_detail(
    conversation_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    row = (
        db.query(_facade().ChatConversation)
        .filter(
            _facade().ChatConversation.id == conversation_id,
            _facade().ChatConversation.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "对话不存在")
    messages = (
        db.query(_facade().ChatMessage)
        .filter(
            _facade().ChatMessage.conversation_id == row.id,
            _facade().ChatMessage.user_id == user.id,
        )
        .order_by(_facade().ChatMessage.created_at.asc(), _facade().ChatMessage.id.asc())
        .all()
    )
    return {
        "id": row.id,
        "title": row.title,
        "provider": row.provider,
        "model": row.model,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "usage": _facade().json.loads(m.usage_json or "{}"),
                "charge_amount": float(m.charge_amount or 0),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@_facade().router.get("/usage")
async def llm_usage(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    rows = (
        db.query(_facade().LlmCallLog)
        .filter(_facade().LlmCallLog.user_id == user.id)
        .order_by(_facade().LlmCallLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "provider": r.provider,
                "model": r.model,
                "status": r.status,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated": bool(r.estimated),
                "charge_amount": float(r.charge_amount or 0),
                "hold_no": r.hold_no,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


class ChatMessageDTO(_facade().BaseModel):
    """content 可为文本/vision 多段；extra=allow 透传 tool_calls/tool_call_id/name。"""

    model_config = _facade().ConfigDict(extra="allow")
    role: str
    content: _facade().Union[str, _facade().List[_facade().Dict[str, _facade().Any]]]


class LlmChatDTO(_facade().BaseModel):
    provider: str
    model: str
    messages: _facade().List[ChatMessageDTO]
    max_tokens: _facade().Optional[int] = _facade().Field(None, ge=1, le=32000)
    conversation_id: _facade().Optional[int] = _facade().Field(None, ge=1)
    allow_failover: bool = True
    tools: _facade().Optional[_facade().List[_facade().Any]] = _facade().Field(
        None, description="OpenAI function-calling tools 定义（透传给上游模型）"
    )
    tool_choice: _facade().Optional[_facade().Any] = _facade().Field(
        None, description="OpenAI tool_choice，如 'auto' 或 {'type':'function','function':{...}}"
    )


class LlmImageDTO(_facade().BaseModel):
    provider: str
    model: str = "gpt-image-1"
    prompt: str = _facade().Field(..., min_length=1, max_length=4000)
    size: str = _facade().Field("1024x1024", max_length=32)
    n: int = _facade().Field(1, ge=1, le=4)


class LlmVideoDTO(_facade().BaseModel):
    provider: str
    model: str
    prompt: str = _facade().Field(..., min_length=1, max_length=4000)
    size: str = _facade().Field("1280x720", max_length=32)
    seconds: int = _facade().Field(5, ge=1, le=30)


class LlmPptxDTO(_facade().BaseModel):
    title: str = _facade().Field("AI 生成 PPT", max_length=120)
    markdown: str = _facade().Field(..., min_length=1, max_length=60000)
    filename: str = _facade().Field("ai-presentation.pptx", max_length=160)


@_facade().router.post("/chat")
async def llm_chat(
    request: _facade().Request,
    body: LlmChatDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    out = await _facade().run_billed_llm_chat(
        request,
        db,
        user,
        provider=body.provider,
        model=body.model.strip(),
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=body.conversation_id,
        allow_failover=bool(body.allow_failover),
    )
    payload = {
        "ok": out["ok"],
        "content": out["content"],
        "conversation_id": out["conversation_id"],
        "usage": out["usage"],
        "charge_amount": out["charge_amount"],
        "hold_no": out["hold_no"],
        "key_source": out["key_source"],
        "billed": out["billed"],
        "provider": out.get("provider"),
        "model": out.get("model"),
    }
    if out.get("failover_from"):
        payload["failover_from"] = out["failover_from"]
        payload["failover_attempts"] = out.get("failover_attempts") or []
    return payload


@_facade().router.post("/chat/stream")
async def llm_chat_stream(
    request: _facade().Request,
    body: LlmChatDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    msgs = [m.model_dump(exclude_none=True) for m in body.messages]
    return await _facade().stream_billed_llm_chat(
        request,
        db,
        user,
        provider=body.provider,
        model=body.model.strip(),
        messages=msgs,
        max_tokens=body.max_tokens,
        conversation_id=body.conversation_id,
        allow_failover=bool(body.allow_failover),
        tools=body.tools,
        tool_choice=body.tool_choice,
    )


@_facade().router.post("/image")
async def llm_image(
    body: LlmImageDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if body.provider not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    (api_key, key_source) = _facade().resolve_api_key(db, user.id, body.provider)
    if not api_key:
        raise _facade().HTTPException(400, f"供应商「{body.provider}」未配置可用 API Key。")
    base = (
        _facade().resolve_base_url(db, user.id, body.provider)
        if body.provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    result = await _facade().image_dispatch(
        body.provider,
        api_key=api_key,
        base_url=base,
        model=body.model.strip() or "gpt-image-1",
        prompt=body.prompt.strip(),
        size=body.size.strip() or "1024x1024",
        n=body.n,
    )
    if not result.get("ok"):
        raise _facade().HTTPException(502, result.get("error") or "image upstream error")
    return {
        "ok": True,
        "images": result.get("images") or [],
        "provider": body.provider,
        "model": body.model,
        "key_source": key_source,
    }


@_facade().router.post("/video")
async def llm_video(
    body: LlmVideoDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if body.provider not in _facade().KNOWN_PROVIDERS:
        raise _facade().HTTPException(400, "unknown provider")
    (api_key, key_source) = _facade().resolve_api_key(db, user.id, body.provider)
    if not api_key:
        raise _facade().HTTPException(400, f"供应商「{body.provider}」未配置可用 API Key。")
    base = (
        _facade().resolve_base_url(db, user.id, body.provider)
        if body.provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    result = await _facade().video_dispatch(
        body.provider,
        api_key=api_key,
        base_url=base,
        model=body.model.strip(),
        prompt=body.prompt.strip(),
        size=body.size.strip() or "1280x720",
        seconds=body.seconds,
    )
    if not result.get("ok"):
        raise _facade().HTTPException(502, result.get("error") or "video upstream error")
    return {
        "ok": True,
        "provider": body.provider,
        "model": body.model,
        "key_source": key_source,
        "job_id": result.get("job_id") or "",
        "status": result.get("status") or "pending",
        "preview_url": result.get("preview_url") or "",
    }


@_facade().router.post("/pptx")
async def llm_pptx(
    body: LlmPptxDTO, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    try:
        blob = _facade().build_pptx_from_markdown(body.markdown, title=body.title)
    except RuntimeError as e:
        raise _facade().HTTPException(503, str(e))
    filename = (
        (body.filename or "ai-presentation.pptx").strip().replace("\\", "_").replace("/", "_")
    )
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"
    quoted = _facade().quote(filename)
    return _facade().Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
