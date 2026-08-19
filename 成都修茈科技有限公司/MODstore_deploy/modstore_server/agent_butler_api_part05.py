# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


def _clip_text(val: _facade().Any, max_len: int) -> str:
    s = str(val or "").strip()
    return s[:max_len] if s else ""


def _validate_intake_draft(raw: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(raw, dict):
        return {}
    out: _facade().Dict[str, _facade().Any] = {}
    if "userRole" in raw:
        v = _facade()._clip_text(raw.get("userRole"), 32)
        if v in _facade()._INTAKE_USER_ROLES:
            out["userRole"] = v
    if "primaryGoal" in raw:
        v = _facade()._clip_text(raw.get("primaryGoal"), 64)
        if v in _facade()._INTAKE_PRIMARY_GOALS:
            out["primaryGoal"] = v
    if "directions" in raw:
        dirs = raw.get("directions")
        if isinstance(dirs, list):
            cleaned = []
            for item in dirs[:8]:
                s = _facade()._clip_text(item, 64)
                if s in _facade()._INTAKE_DIRECTIONS and s not in cleaned:
                    cleaned.append(s)
            if cleaned:
                out["directions"] = cleaned
    if "timeline" in raw:
        v = _facade()._clip_text(raw.get("timeline"), 32)
        if v in _facade()._INTAKE_TIMELINES:
            out["timeline"] = v
    if "budget" in raw:
        v = _facade()._clip_text(raw.get("budget"), 32)
        if v in _facade()._INTAKE_BUDGETS:
            out["budget"] = v
    if "needIntegration" in raw:
        v = _facade()._clip_text(raw.get("needIntegration"), 8)
        if v in _facade()._INTAKE_NEED_INTEGRATION:
            out["needIntegration"] = v
    for key, max_len in _facade()._INTAKE_TEXT_LIMITS.items():
        if key in raw:
            v = _facade()._clip_text(raw.get(key), max_len)
            if v:
                out[key] = v
    return out


def _parse_intake_llm_json(text: str) -> _facade().Dict[str, _facade().Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = _facade().json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = _facade().json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
    return {}


@_facade().router.post("/corp-intake-fill")
async def butler_corp_intake_fill(
    request: _facade().Request,
    body: _facade().CorpIntakeFillDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """联系页问卷：根据用户描述生成结构化草稿（公开、限流、无工具）。"""
    _facade()._corp_chat_rate_allow(_facade()._public_contact_client_key(request))
    (provider, model, api_key, base_url) = _facade()._resolve_corp_credentials(db)
    draft_hint = ""
    if body.current_draft:
        try:
            draft_hint = _facade().json.dumps(body.current_draft, ensure_ascii=False)[:1500]
        except Exception:
            draft_hint = ""
    user_content = body.message.strip()
    if draft_hint:
        user_content += f"\n\n当前已填草稿（JSON）：{draft_hint}"
    if body.page_summary:
        user_content += f"\n\n页面上下文：{body.page_summary[:2000]}"
    msgs: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {"role": "system", "content": _facade().CORP_INTAKE_FILL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content[:3500]},
    ]
    try:
        raw_response = await _facade().chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=msgs,
            max_tokens=900,
            response_format={"type": "json_object"},
            forbid_reasoning_fallback=True,
        )
        if not raw_response.get("ok"):
            raise RuntimeError(raw_response.get("error") or "corp-intake-fill failed")
        text = (raw_response.get("content") or "").strip()
    except Exception as exc:
        _facade().logger.warning("corp-intake-fill LLM failed: %s", exc)
        raise _facade().HTTPException(503, "智能预填暂不可用，请直接在左侧表单填写。") from exc
    parsed = _facade()._parse_intake_llm_json(text)
    reply = (
        _facade()._clip_text(parsed.get("reply"), 500)
        or "已根据您的描述整理问卷草稿，请在左侧核对。"
    )
    draft = _facade()._validate_intake_draft(parsed.get("draft"))
    if not draft:
        _facade().logger.warning(
            "corp-intake-fill empty draft after parse (provider=%s model=%s text_len=%s)",
            provider,
            model,
            len(text),
        )
    return {"success": True, "reply": reply, "draft": draft}


@_facade().router.post("/chat")
async def butler_chat(
    request: _facade().Request,
    body: _facade().ButlerChatDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """非流式 Butler 对话。"""
    (provider, model, api_key, key_source, base_url) = _facade()._resolve_butler_credentials(
        db, user.id
    )
    is_byok = key_source == "user_override"
    msgs = _facade()._build_messages(body, body.page_context, user=user, db=db)
    if not msgs:
        raise _facade().HTTPException(400, "messages 不能为空")
    request_id = _facade().new_request_id()
    _facade().enforce_risk_limits(db, user.id, provider, model, msgs, request)
    wallet = _facade().JavaWalletClient()
    if is_byok:
        hold = _facade().WalletHold(
            hold_no=f"byok-{request_id}", amount=_facade().Decimal("0"), enabled=False
        )
    else:
        preauth = _facade().estimate_preauthorization(db, provider, model, msgs, body.max_tokens)
        hold = await wallet.preauthorize(
            _facade().authorization_header(request), preauth, provider, model, request_id
        )
    conv = _facade()._get_or_create_conversation(db, user.id, body.conversation_id, provider, model)
    try:
        from modstore_server.infrastructure.http_clients import get_external_client
        from modstore_server.llm_chat_proxy import _normalize_openai_base

        tool_resp = None
        tools_schema = _facade()._butler_tools_for_user(user)
        if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            try:
                base = _normalize_openai_base(provider, base_url)
                url = f"{base}/chat/completions"
                req_body: _facade().Dict[str, _facade().Any] = {
                    "model": model,
                    "messages": msgs,
                    "tools": tools_schema,
                    "tool_choice": "auto",
                }
                if body.max_tokens:
                    req_body["max_tokens"] = body.max_tokens
                r = await get_external_client().post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=req_body,
                    timeout=120.0,
                )
                if r.status_code < 400:
                    tool_resp = r.json()
            except Exception as e:
                _facade().logger.warning("butler tool call failed, fallback to plain: %s", e)
        if tool_resp:
            raw_response = tool_resp
            choice0 = (tool_resp.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            text = msg.get("content") or ""
            tool_calls_raw = msg.get("tool_calls") or []
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "args": _facade()._safe_json(tc.get("function", {}).get("arguments", "{}")),
                }
                for tc in tool_calls_raw
            ]
            usage = tool_resp.get("usage") or {}
        else:
            raw_response = await _facade().chat_dispatch(
                provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=msgs,
                max_tokens=body.max_tokens,
            )
            if not raw_response.get("ok"):
                raise RuntimeError(raw_response.get("error") or "butler chat failed")
            text = raw_response.get("content", "")
            tool_calls = []
            usage = raw_response.get("usage") or {}
        (page_tool_calls, readonly_brief) = _facade()._partition_butler_tool_calls(
            tool_calls, user=user, db=db
        )
        tool_calls = page_tool_calls
        if readonly_brief:
            text = ((text or "").strip() + "\n\n" + readonly_brief).strip()
    except Exception as exc:
        await wallet.release(hold)
        _facade().save_failure_log(db, user.id, provider, model, request_id, str(exc), conv.id)
        raise _facade().HTTPException(500, f"LLM 调用失败：{exc}")
    usage_obj = _facade().usage_from_response({"usage": usage}, msgs, [text])
    charge = _facade().calculate_charge(db, provider, model, usage_obj)
    if not is_byok:
        await wallet.settle(
            hold, _facade().authorization_header(request), charge, provider, model, request_id
        )
    _facade().save_success_log(
        db, user.id, provider, model, request_id, usage_obj, float(charge), conv.id
    )
    db.add(
        _facade().ChatMessage(
            conversation_id=conv.id,
            user_id=user.id,
            role="assistant",
            content=text,
            provider=provider,
            model=model,
            charge_amount=float(charge),
        )
    )
    db.commit()
    return {
        "text": text,
        "tool_calls": tool_calls,
        "conversation_id": conv.id,
        "charge_amount": float(charge),
        "billed": not is_byok,
    }


@_facade().router.post("/chat/stream")
async def butler_chat_stream(
    request: _facade().Request,
    body: _facade().ButlerChatDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """SSE 流式 Butler 对话（管理员工具路径降级为一次非流式完成后再 SSE）。"""
    if bool(getattr(user, "is_admin", False)):
        result = await _facade().butler_chat(request, body, db=db, user=user)

        async def admin_event_stream():
            text = str(result.get("text") or "")
            if text:
                yield f"data: {_facade().json.dumps({'text': text, 'done': False}, ensure_ascii=False)}\n\n"
            yield f"data: {_facade().json.dumps({'text': '', 'done': True, 'conversation_id': result.get('conversation_id'), 'charge_amount': result.get('charge_amount'), 'tool_calls': result.get('tool_calls') or []}, ensure_ascii=False)}\n\n"

        return _facade().StreamingResponse(admin_event_stream(), media_type="text/event-stream")
    (provider, model, api_key, key_source, base_url) = _facade()._resolve_butler_credentials(
        db, user.id
    )
    msgs = _facade()._build_messages(body, body.page_context, user=user, db=db)
    is_byok = key_source == "user_override"
    if not msgs:
        raise _facade().HTTPException(400, "messages 不能为空")
    request_id = _facade().new_request_id()
    _facade().enforce_risk_limits(db, user.id, provider, model, msgs, request)
    wallet = _facade().JavaWalletClient()
    if is_byok:
        hold = _facade().WalletHold(
            hold_no=f"byok-{request_id}", amount=_facade().Decimal("0"), enabled=False
        )
    else:
        preauth = _facade().estimate_preauthorization(db, provider, model, msgs, body.max_tokens)
        hold = await wallet.preauthorize(
            _facade().authorization_header(request), preauth, provider, model, request_id
        )
    conv = _facade()._get_or_create_conversation(db, user.id, body.conversation_id, provider, model)

    async def event_stream():
        collected = []
        try:
            async for chunk in _facade().chat_dispatch_stream(
                provider, api_key, model, msgs, base_url=base_url, max_tokens=body.max_tokens
            ):
                if isinstance(chunk, str):
                    collected.append(chunk)
                    yield f"data: {_facade().json.dumps({'text': chunk, 'done': False}, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, dict) and chunk.get("done"):
                    usage = chunk.get("usage") or {}
                    usage_obj = _facade().usage_from_response({"usage": usage}, msgs, collected)
                    charge = _facade().calculate_charge(db, provider, model, usage_obj)
                    if not is_byok:
                        await wallet.settle(
                            hold,
                            _facade().authorization_header(request),
                            charge,
                            provider,
                            model,
                            request_id,
                        )
                    full_text = "".join(collected)
                    _facade().save_success_log(
                        db, user.id, provider, model, request_id, usage_obj, float(charge), conv.id
                    )
                    db.add(
                        _facade().ChatMessage(
                            conversation_id=conv.id,
                            user_id=user.id,
                            role="assistant",
                            content=full_text,
                            provider=provider,
                            model=model,
                            charge_amount=float(charge),
                        )
                    )
                    db.commit()
                    yield f"data: {_facade().json.dumps({'text': '', 'done': True, 'conversation_id': conv.id, 'charge_amount': float(charge)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            await wallet.release(hold)
            _facade().save_failure_log(db, user.id, provider, model, request_id, str(exc), conv.id)
            yield f"data: {_facade().json.dumps({'error': str(exc), 'done': True}, ensure_ascii=False)}\n\n"

    return _facade().StreamingResponse(event_stream(), media_type="text/event-stream")


@_facade().router.post("/actions")
async def record_butler_action(
    body: _facade().ButlerActionDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """记录管家操作审计。"""
    try:
        db.add(
            _facade().ButlerAction(
                user_id=user.id,
                route=body.route or "",
                action=body.action,
                args_json=_facade().json.dumps(body.args or {}, ensure_ascii=False),
                risk=body.risk,
                status=body.status,
            )
        )
        db.commit()
    except Exception as exc:
        _facade().logger.warning("butler action log failed: %s", exc)
    return {"ok": True}


@_facade().router.get("/skills")
async def list_butler_skills(
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """返回 butler 类型的 E-Skill 列表（供前端运行时加载）。"""
    try:
        from modstore_server.models import ESkill

        rows = db.query(ESkill).filter(ESkill.domain == "butler").all()
        return {
            "items": [
                {
                    "id": r.id,
                    "skill_id": f"eskill_{r.id}",
                    "name": r.name,
                    "description": r.description,
                    "version": str(r.active_version),
                    "kind": "butler",
                    "trigger_keywords": [],
                    "trigger_intent": [],
                    "permission": "execute",
                    "is_active": True,
                    "usage_count": 0,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
        }
    except Exception as exc:
        _facade().logger.warning("list butler skills failed: %s", exc)
        return {"items": []}


@_facade().router.patch("/skills/{skill_id}")
async def update_butler_skill_active(
    skill_id: int,
    body: _facade().ButlerSkillActiveDTO,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """更新 butler 技能激活状态（管理员操作）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可操作")
    try:
        from modstore_server.models import ESkill

        row = db.query(ESkill).filter(ESkill.id == skill_id).first()
        if not row:
            raise _facade().HTTPException(404, "技能不存在")
        db.commit()
        return {"ok": True, "id": skill_id, "is_active": body.is_active}
    except _facade().HTTPException:
        raise
    except Exception as exc:
        raise _facade().HTTPException(500, str(exc)) from exc
