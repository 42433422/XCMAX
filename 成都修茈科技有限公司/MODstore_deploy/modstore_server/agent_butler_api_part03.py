# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


class ButlerActionDTO(_facade().BaseModel):
    route: str = ""
    action: str
    args: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    risk: str = "low"
    status: str = "success"


class ButlerSkillActiveDTO(_facade().BaseModel):
    is_active: bool


def _resolve_butler_credentials(db: _facade().Session, user_id: int):
    """解析管家使用的 LLM 凭证（复用用户默认偏好）。"""
    user = db.query(_facade().User).filter(_facade().User.id == user_id).first()
    if not user:
        raise _facade().HTTPException(401, "用户不存在")
    prefs: _facade().Dict[str, _facade().Any] = {}
    raw = getattr(user, "default_llm_json", None) or ""
    if raw.strip():
        try:
            prefs = _facade().json.loads(raw)
        except Exception:
            pass
    provider = str(prefs.get("provider") or "").strip()
    model = str(prefs.get("model") or "").strip()
    if not provider or provider not in _facade().KNOWN_PROVIDERS:
        for p in _facade().KNOWN_PROVIDERS:
            (key, _) = _facade().resolve_api_key(db, user_id, p)
            if key:
                provider = p
                break
        if not provider:
            raise _facade().HTTPException(
                400,
                "未配置可用的 LLM 供应商。请在账户页面 → LLM 设置中配置 API Key，或联系管理员。",
            )
    if not model:
        model = "gpt-4o-mini"
    (api_key, key_source) = _facade().resolve_api_key(db, user_id, provider)
    if not api_key:
        raise _facade().HTTPException(
            400, f"供应商「{provider}」未配置可用 API Key。请在账户页面绑定 API Key。"
        )
    base_url = (
        _facade().resolve_base_url(db, user_id, provider)
        if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    return (provider, model, api_key, key_source, base_url)


def _build_messages(
    body: _facade().ButlerChatDTO,
    page_context: str | None,
    *,
    user: _facade().User | None = None,
    db: _facade().Session | None = None,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """组装最终 messages：小C SSOT 人设 + 对话对象 + 管理端知识库 + 页面上下文。"""
    from modstore_server.xiaoc_cs_ssot import (
        format_visitor_block,
        knowledge_block_for_query,
        last_user_text,
        resolve_user_identity,
        xiaoc_system_prompt,
    )

    system_content = xiaoc_system_prompt(mode="admin")
    if "enhance_current_page" in _facade().BUTLER_SYSTEM_PROMPT:
        system_content += "\n\n【工具能力补充】\n" + "\n".join(
            (
                line
                for line in _facade().BUTLER_SYSTEM_PROMPT.splitlines()
                if line.startswith("6.")
                or line.startswith("可识别")
                or line.startswith("- /workbench")
                or line.startswith("操作原则")
                or line.startswith("- 低风险")
                or line.startswith("- 中风险")
                or line.startswith("- 高风险")
                or line.startswith("回复要简洁")
            )
        )
    if user is not None:
        vb = format_visitor_block(resolve_user_identity(user, db=db, source="butler"))
        if vb:
            system_content += f"\n\n{vb}"
    user_q = last_user_text(body.messages)
    kb = knowledge_block_for_query(user_q, mode="admin") if user_q else ""
    if kb:
        system_content += f"\n\n{kb}"
    if page_context:
        system_content += f"\n\n当前页面上下文：\n{page_context}"
    msgs: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {"role": "system", "content": system_content}
    ]
    for m in body.messages:
        if m.role == "system":
            continue
        msgs.append({"role": m.role, "content": m.content})
    return msgs


def _corp_chat_rate_allow(client_key: str) -> None:
    now = _facade().time.time()
    cutoff = now - _facade()._CORP_CHAT_WINDOW_SEC
    bucket = _facade()._CORP_CHAT_TIMES[client_key]
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _facade()._CORP_CHAT_LIMIT:
        raise _facade().HTTPException(status_code=429, detail="咨询过于频繁，请稍后再试")
    bucket.append(now)


def _resolve_corp_credentials(db: _facade().Session):
    """官网公开咨询 LLM 凭证。

    优先级：
    1. 显式 ``BUTLER_CORP_*`` 钉死（运维手动覆盖）
    2. 平台运行时路由（``llm-ops-engineer`` / ``runtime_route.json``）
    3. ``BUTLER_CORP_USER_ID`` / 分 provider 的 corp key
    4. 遗留 ``BUTLER_QQ_LLM_*``
    """
    provider = (_facade().os.environ.get("BUTLER_CORP_PROVIDER") or "").strip()
    model = (_facade().os.environ.get("BUTLER_CORP_MODEL") or "").strip()
    api_key = (_facade().os.environ.get("BUTLER_CORP_API_KEY") or "").strip()
    base_url = None
    user_id_raw = (_facade().os.environ.get("BUTLER_CORP_USER_ID") or "").strip()
    if provider and api_key:
        if not model:
            model = "gpt-4o-mini"
        if base_url is None and provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            from modstore_server.llm_key_resolver import platform_base_url

            base_url = platform_base_url(provider)
            if base_url is None and user_id_raw.isdigit():
                base_url = _facade().resolve_base_url(db, int(user_id_raw), provider)
        return (provider, model, api_key, base_url)
    try:
        from modstore_server.llm_key_resolver import platform_api_key, platform_base_url
        from modstore_server.services.llm import resolve_platform_bench_llm

        (route_provider, route_model) = resolve_platform_bench_llm()
        if route_provider and route_model:
            route_key = platform_api_key(route_provider)
            if route_key:
                return (route_provider, route_model, route_key, platform_base_url(route_provider))
    except Exception:
        _facade().logger.debug("corp-chat: platform runtime route unavailable", exc_info=True)
    if not api_key and user_id_raw.isdigit():
        uid = int(user_id_raw)
        if not provider:
            for p in _facade().KNOWN_PROVIDERS:
                (key, _) = _facade().resolve_api_key(db, uid, p)
                if key:
                    provider = p
                    break
        if provider:
            (api_key, _) = _facade().resolve_api_key(db, uid, provider)
            if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
                base_url = _facade().resolve_base_url(db, uid, provider)
    if not provider:
        for p in _facade().KNOWN_PROVIDERS:
            if _facade().os.environ.get(f"BUTLER_CORP_API_KEY_{p.upper()}"):
                provider = p
                api_key = _facade().os.environ.get(f"BUTLER_CORP_API_KEY_{p.upper()}", "").strip()
                break
        if not provider:
            provider = "openai"
    if not api_key:
        qq_key = (_facade().os.environ.get("BUTLER_QQ_LLM_API_KEY") or "").strip()
        if qq_key:
            api_key = qq_key
            if not (_facade().os.environ.get("BUTLER_CORP_PROVIDER") or "").strip():
                provider = (
                    _facade().os.environ.get("BUTLER_QQ_LLM_PROVIDER") or provider or "openai"
                ).strip()
            if not model:
                qq_model = (_facade().os.environ.get("BUTLER_QQ_LLM_MODEL") or "").strip()
                if qq_model:
                    model = qq_model
            if base_url is None:
                qq_base = (_facade().os.environ.get("BUTLER_QQ_LLM_BASE_URL") or "").strip()
                if qq_base:
                    base_url = qq_base
    if not model:
        model = "gpt-4o-mini"
    if not api_key:
        raise _facade().HTTPException(503, "官网咨询助手暂不可用，请通过联系我们页留言或稍后再试。")
    if base_url is None and provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        from modstore_server.llm_key_resolver import platform_base_url

        base_url = platform_base_url(provider)
        if base_url is None and user_id_raw.isdigit():
            base_url = _facade().resolve_base_url(db, int(user_id_raw), provider)
    return (provider, model, api_key, base_url)


def _build_corp_messages(
    body: _facade().CorpChatDTO,
    *,
    user: _facade().User | None = None,
    db: _facade().Session | None = None,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """官网公开咨询：统一小C 人设 + 对话对象 + 管理端 persy 知识库。"""
    from modstore_server.xiaoc_cs_ssot import (
        format_visitor_block,
        identity_from_guest,
        knowledge_block_for_query,
        last_user_text,
        resolve_user_identity,
        xiaoc_system_prompt,
    )

    system_content = xiaoc_system_prompt(mode="corp")
    if user is not None:
        identity = resolve_user_identity(
            user, db=db, source="corp", visitor_id=body.visitor_id or ""
        )
    else:
        identity = identity_from_guest(
            visitor_id=body.visitor_id or "", visitor_label=body.visitor_label or "", source="corp"
        )
    vb = format_visitor_block(identity)
    if vb:
        system_content += f"\n\n{vb}"
    user_q = last_user_text(body.messages)
    kb = knowledge_block_for_query(user_q, mode="corp") if user_q else ""
    if kb:
        system_content += f"\n\n{kb}"
    if body.page_context:
        system_content += (
            f"\n\n当前页面（{body.page_id or 'unknown'}）上下文：\n{body.page_context[:3500]}"
        )
    msgs: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {"role": "system", "content": system_content}
    ]
    for m in body.messages:
        if m.role == "system":
            continue
        msgs.append({"role": m.role, "content": m.content})
    return msgs


def _get_or_create_conversation(
    db: _facade().Session, user_id: int, conversation_id: int | None, provider: str, model: str
) -> _facade().ChatConversation:
    if conversation_id:
        conv = (
            db.query(_facade().ChatConversation)
            .filter(
                _facade().ChatConversation.id == conversation_id,
                _facade().ChatConversation.user_id == user_id,
            )
            .first()
        )
        if conv:
            return conv
    conv = _facade().ChatConversation(
        user_id=user_id, title="数字管家对话", provider=provider, model=model
    )
    db.add(conv)
    db.flush()
    return conv


class CsSsotRetrieveDTO(_facade().BaseModel):
    query: str = _facade().Field(..., min_length=1, max_length=4000)
    top_k: int = 5


@_facade().router.get("/cs-ssot/policy")
async def butler_cs_ssot_policy(mode: str = "admin"):
    """公开可读：小C 分角色权限契约（external / market_cs / admin）。"""
    from modstore_server.xiaoc_cs_ssot import XIAOC_PERMISSIONS, permission_policy

    key = (mode or "admin").strip().lower()
    if key in ("corp", "public", "官网"):
        key = "external"
    if key not in XIAOC_PERMISSIONS:
        key = "admin"
    return {"ok": True, "policy": permission_policy(mode=key), "modes": list(XIAOC_PERMISSIONS)}


@_facade().router.post("/cs-ssot/retrieve")
async def butler_cs_ssot_retrieve(
    body: CsSsotRetrieveDTO, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    """已登录市场/管理端：按身份检索公开库（管理员另含内部库）。"""
    from modstore_server.xiaoc_cs_ssot import PUBLIC_DATASET_ID, retrieve_knowledge_for_mode

    mode = "admin" if bool(getattr(user, "is_admin", False)) else "market_cs"
    chunks = retrieve_knowledge_for_mode(body.query, mode=mode, top_k=body.top_k)
    return {
        "ok": True,
        "dataset_id": PUBLIC_DATASET_ID,
        "mode": mode,
        "query": body.query,
        "chunks": chunks,
        "ssot": "xiaoc_kb_isolation",
    }


@_facade().router.post("/corp-chat")
async def butler_corp_chat(
    request: _facade().Request,
    body: _facade().CorpChatDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    authorization: str | None = _facade().Header(default=None),
):
    """官网公开咨询（无登录、无钱包扣费、无工具调用）。"""
    _facade()._corp_chat_rate_allow(_facade()._public_contact_client_key(request))
    (provider, model, api_key, base_url) = _facade()._resolve_corp_credentials(db)
    optional_user: _facade().User | None = None
    try:
        from modstore_server.api.auth_deps import get_optional_user

        optional_user = get_optional_user(authorization)
    except Exception:
        optional_user = None
    msgs = _facade()._build_corp_messages(body, user=optional_user, db=db)
    if not any((m.get("role") == "user" for m in msgs)):
        raise _facade().HTTPException(400, "messages 须包含至少一条 user 消息")
    try:
        raw_response = await _facade().chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=msgs,
            max_tokens=body.max_tokens or 512,
        )
        if not raw_response.get("ok"):
            raise RuntimeError(raw_response.get("error") or "corp-chat failed")
        text = (raw_response.get("content") or "").strip()
    except Exception as exc:
        _facade().logger.warning("corp-chat LLM failed: %s", exc)
        raise _facade().HTTPException(503, "暂时无法回答，请通过联系我们页留言。") from exc
    if not text:
        text = (
            "抱歉，我暂时无法回答这个问题。您可浏览产品中心 /services.html 或留言 /contact.html。"
        )
    return {"success": True, "content": text, "message": text}


@_facade().router.post("/corp-translate")
async def butler_corp_translate(
    request: _facade().Request,
    body: _facade().CorpTranslateDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """朗读字幕短译：中文 → 英文（公开、限流、仅返回译文）。"""
    _facade()._corp_chat_rate_allow(_facade()._public_contact_client_key(request))
    text = (body.text or "").strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    target = (body.target or "en").strip().lower()
    if target != "en":
        raise _facade().HTTPException(400, "仅支持 target=en")
    (provider, model, api_key, base_url) = _facade()._resolve_corp_credentials(db)
    if not api_key:
        raise _facade().HTTPException(503, "翻译暂不可用")
    msgs = [
        {
            "role": "system",
            "content": "You are a concise translator. Translate the user's Chinese text into natural English. Output ONLY the English translation, no quotes, no explanation.",
        },
        {"role": "user", "content": text[:500]},
    ]
    try:
        raw_response = await _facade().chat_dispatch(
            provider, api_key=api_key, base_url=base_url, model=model, messages=msgs, max_tokens=180
        )
        if not raw_response.get("ok"):
            raise RuntimeError(raw_response.get("error") or "translate failed")
        en = (raw_response.get("content") or "").strip().strip('"').strip("'")
    except Exception as exc:
        _facade().logger.warning("corp-translate failed: %s", exc)
        raise _facade().HTTPException(503, "翻译暂不可用") from exc
    if not en:
        raise _facade().HTTPException(503, "翻译为空")
    return {"success": True, "data": {"translation": en, "target": "en"}}


@_facade().router.post("/corp-tts")
async def butler_corp_tts(request: _facade().Request, body: _facade().CorpTtsDTO):
    """官网公开 TTS：优先 MiMo，失败回退 Edge 神经音；不使用浏览器系统 TTS。"""
    import base64

    _facade()._corp_chat_rate_allow(_facade()._public_contact_client_key(request))
    text = (body.text or "").strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    try:
        from modstore_server.mimo_tts_service import DEFAULT_VOICE as MIMO_VOICE
        from modstore_server.mimo_tts_service import synthesize_mimo_tts_async

        voice = (body.voice or "").strip() or MIMO_VOICE
        (audio, err, meta) = await synthesize_mimo_tts_async(text, voice=voice)
        if audio and (not err):
            mime = str(meta.get("mime") or "audio/wav")
            b64 = base64.b64encode(audio).decode("ascii")
            return {
                "success": True,
                "data": {
                    "audioBase64": f"data:{mime};base64,{b64}",
                    "provider": "mimo",
                    "voice": meta.get("voice") or voice,
                },
            }
        if err:
            _facade().logger.info("corp-tts MiMo unavailable, fallback Edge: %s", err)
    except Exception as exc:
        _facade().logger.warning("corp-tts MiMo failed, fallback Edge: %s", exc)
    try:
        from modstore_server.edge_tts_service import DEFAULT_VOICE as EDGE_VOICE
        from modstore_server.edge_tts_service import rate_str_from_float, stream_audio

        edge_voice = EDGE_VOICE
        chunks: list[bytes] = []
        async for data in stream_audio(text, edge_voice, rate_str_from_float(1.05)):
            if data:
                chunks.append(data)
        mp3 = b"".join(chunks)
        if not mp3:
            raise RuntimeError("edge-tts empty")
        b64 = base64.b64encode(mp3).decode("ascii")
        return {
            "success": True,
            "data": {
                "audioBase64": f"data:audio/mpeg;base64,{b64}",
                "provider": "edge",
                "voice": edge_voice,
            },
        }
    except Exception as exc:
        _facade().logger.warning("corp-tts Edge failed: %s", exc)
        raise _facade().HTTPException(503, "语音合成暂不可用") from exc
