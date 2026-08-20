# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _memory_real(
    config: _facade().Dict[str, _facade().Any],
    ctx: _facade().Dict[str, _facade().Any],
    session,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    mem_cfg = _facade()._get_section(config, "memory")
    employee_id = ctx["employee_id"]
    result: _facade().Dict[str, _facade().Any] = {
        "session": {"employee_id": employee_id},
        "long_term": None,
    }
    short_term_cfg = mem_cfg.get("short_term") or {}
    if short_term_cfg.get("enabled", True):
        q = session.query(_facade().EmployeeExecutionMetric).filter(
            _facade().EmployeeExecutionMetric.employee_id == employee_id
        )
        if user_id > 0:
            q = q.filter(_facade().EmployeeExecutionMetric.user_id == user_id)
        recent = q.order_by(_facade().EmployeeExecutionMetric.id.desc()).limit(5).all()
        result["session"]["recent_tasks"] = [
            {
                "task": r.task,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ]
    long_term_cfg = mem_cfg.get("long_term") or {}
    if long_term_cfg.get("enabled", False):
        result["long_term"] = _facade()._memory_long_term_chroma(
            employee_id, ctx.get("input_data") or {}, long_term_cfg
        )
    try:
        from modstore_server.models_project_context import gather_for_employee

        result["project_context"] = gather_for_employee(
            employee_id=employee_id, input_data=ctx.get("input_data") or {}
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("attach project_context to memory failed", exc_info=True)
    return result


async def _cognition_real(
    config: _facade().Dict[str, _facade().Any],
    perceived: _facade().Dict[str, _facade().Any],
    memory: _facade().Dict[str, _facade().Any],
    session,
    user_id: int,
    *,
    employee_id: str = "",
    task: str = "",
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    cog_cfg = _facade()._get_section(config, "cognition")
    agent = cog_cfg.get("agent") if isinstance(cog_cfg.get("agent"), dict) else cog_cfg
    system_prompt = agent.get("system_prompt", "你是智能员工助手")
    if employee_id:
        try:
            from modstore_server.prompt_evolution_ab import get_effective_system_prompt

            system_prompt = get_effective_system_prompt(str(employee_id), str(system_prompt))
        except RECOVERABLE_ERRORS:
            pass
    if str(task or "").strip() and (
        not _facade()._is_all_hands_cognition_context(
            perceived.get("normalized_input") if isinstance(perceived, dict) else {}
        )
    ):
        system_prompt = f"{system_prompt.rstrip()}\n\n{_facade()._PHASE_D_PROTOCOL_APPEND}"
    model_cfg = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    normalized_inp = perceived.get("normalized_input", {})
    if not isinstance(normalized_inp, dict):
        normalized_inp = {}
    all_hands_cognition = _facade()._is_all_hands_cognition_context(normalized_inp)
    if all_hands_cognition and str(task or "").strip():
        system_prompt = (
            f"{system_prompt.rstrip()}\n\n{_facade()._ALL_HANDS_COGNITION_SYSTEM_APPEND}"
        )
    use_platform_dispatch = bool(bench_llm_override)
    if not bench_llm_override:
        try:
            from modstore_server.platform_llm_scope import platform_llm_scope_active

            if platform_llm_scope_active():
                from modstore_server.services.llm import resolve_platform_bench_llm

                _pp, _pm = resolve_platform_bench_llm()
                if _pp and _pm:
                    bench_llm_override = (_pp, _pm)
                    use_platform_dispatch = True
        except RECOVERABLE_ERRORS:
            pass
    if not bench_llm_override and int(user_id or 0) <= 0:
        from modstore_server.services.llm import resolve_platform_bench_llm

        _pp, _pm = resolve_platform_bench_llm()
        if not _pp or not _pm:
            return {
                "reasoning": "",
                "error": "平台自动驾驶选择模型失败：未配置可用 LLM（请配置平台 API Key 或 MODSTORE_EMPLOYEE_BENCH_PROVIDER / MODSTORE_EMPLOYEE_BENCH_MODEL）",
                "input": perceived.get("normalized_input", {}),
                "memory": memory,
                "knowledge": {"enabled": False, "items": [], "error": ""},
                "provider": "auto",
                "model": "auto",
            }
        bench_llm_override = (_pp, _pm)
        use_platform_dispatch = True
    if bench_llm_override:
        provider, model_name = bench_llm_override
    else:
        provider = str(model_cfg.get("provider") or "auto").strip()
        model_name = str(model_cfg.get("model_name") or "auto").strip()
        wants_auto = provider.lower() == "auto" or model_name.lower() == "auto"
        if wants_auto:
            from modstore_server.mod_scaffold_runner import (
                resolve_llm_provider_model_auto,
            )

            uid = int(user_id or 0)
            if uid <= 0:
                from modstore_server.services.llm import resolve_platform_bench_llm

                rp, rm = resolve_platform_bench_llm()
                if not rp or not rm:
                    return {
                        "reasoning": "",
                        "error": "自动选择模型失败：平台未配置可用 LLM（请配置平台 API Key 或 MODSTORE_EMPLOYEE_BENCH_PROVIDER / MODSTORE_EMPLOYEE_BENCH_MODEL）",
                        "input": perceived.get("normalized_input", {}),
                        "memory": memory,
                        "knowledge": {"enabled": False, "items": [], "error": ""},
                        "provider": "auto",
                        "model": "auto",
                    }
                provider, model_name = (rp, rm)
                use_platform_dispatch = True
            else:
                urow = session.query(_facade().User).filter(_facade().User.id == uid).first()
                if not urow:
                    return {
                        "reasoning": "",
                        "error": "自动选择模型失败：找不到用户记录",
                        "input": perceived.get("normalized_input", {}),
                        "memory": memory,
                        "knowledge": {"enabled": False, "items": [], "error": ""},
                        "provider": "auto",
                        "model": "auto",
                    }
                rp, rm, perr = await resolve_llm_provider_model_auto(session, urow, None, None)
                if perr or not rp or (not rm):
                    err_msg = perr or "无法解析可用 LLM"
                    return {
                        "reasoning": "",
                        "error": err_msg,
                        "input": perceived.get("normalized_input", {}),
                        "memory": memory,
                        "knowledge": {"enabled": False, "items": [], "error": ""},
                        "provider": "auto",
                        "model": "auto",
                    }
                provider, model_name = (rp, rm)
    max_tokens = int(model_cfg.get("max_tokens") or 4000)
    messages = [{"role": "system", "content": system_prompt}]
    p_cfg = _facade()._get_section(config, "perception")
    vis_cfg = p_cfg.get("vision") if isinstance(p_cfg.get("vision"), dict) else {}
    vision_enabled = bool(vis_cfg.get("enabled", True))
    mem_session = memory.get("session") if isinstance(memory, dict) else None
    session_context_json = (
        _facade().json.dumps(mem_session, ensure_ascii=False) if mem_session else ""
    )
    if all_hands_cognition and str(task or "").strip():
        user_input = _facade()._build_all_hands_cognition_user_message(
            task, normalized_inp, session_context_json=session_context_json
        )
    else:
        _task_text = str(task or "").strip()
        _inp_json = _facade().json.dumps(normalized_inp, ensure_ascii=False)
        if _task_text:
            user_input = f"任务：{_task_text}\n\n输入数据：{_inp_json}"
        else:
            user_input = _inp_json
        if session_context_json:
            user_input = f"{user_input}\n\n[session_context]\n{session_context_json}"
    v_urls: _facade().List[str] = []
    if isinstance(perceived, dict):
        vu = perceived.get("vision_data_urls")
        if isinstance(vu, list):
            v_urls = [str(u).strip() for u in vu if isinstance(u, str) and str(u).strip()]
    if vision_enabled and v_urls:
        parts: _facade().List[_facade().Dict[str, _facade().Any]] = [
            {"type": "text", "text": user_input}
        ]
        for u in v_urls[:6]:
            parts.append({"type": "image_url", "image_url": {"url": u}})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_input})
    knowledge_cfg = cog_cfg.get("knowledge") if isinstance(cog_cfg.get("knowledge"), dict) else {}
    rag_meta: _facade().Dict[str, _facade().Any] = {
        "enabled": False,
        "items": [],
        "error": "",
    }
    if knowledge_cfg.get("enabled"):
        try:
            from modstore_server import rag_service

            top_k = int(knowledge_cfg.get("top_k") or 6)
            min_score = float(knowledge_cfg.get("min_score") or 0.0)
            collection_ids = knowledge_cfg.get("collection_ids")
            query_text = str(task or user_input or "").strip()[:1500]
            chunks = await rag_service.retrieve(
                user_id=int(user_id or 0),
                query=query_text,
                employee_id=str(employee_id or "") or None,
                extra_collection_ids=collection_ids if isinstance(collection_ids, list) else None,
                top_k=top_k,
                min_score=min_score,
            )
            messages = rag_service.inject_rag_into_messages(messages, chunks)
            rag_meta = {
                "enabled": True,
                "items": [c.to_dict() for c in chunks],
                "count": len(chunks),
            }
        except RECOVERABLE_ERRORS as e:
            _facade().logger.warning("cognition.knowledge retrieve 失败: %s", e)
            rag_meta = {"enabled": True, "items": [], "error": str(e)}
    from modstore_server.mod_employee_agent_runner import _llm_timeout_seconds

    llm_timeout_s = _llm_timeout_seconds()
    try:
        if use_platform_dispatch:
            from modstore_server.services.llm import chat_dispatch_via_platform_only

            result = await _facade().asyncio.wait_for(
                chat_dispatch_via_platform_only(
                    provider, model_name, messages, max_tokens=max_tokens
                ),
                timeout=llm_timeout_s,
            )
        else:
            result = await _facade().asyncio.wait_for(
                _facade().chat_dispatch_via_session(
                    session,
                    user_id,
                    provider,
                    model_name,
                    messages,
                    max_tokens=max_tokens,
                ),
                timeout=llm_timeout_s,
            )
    except _facade().asyncio.TimeoutError:
        result = {
            "ok": False,
            "error": f"employee cognition LLM timeout ({int(llm_timeout_s)}s)",
        }
    if not result.get("ok"):
        err = str(result.get("error") or "llm call failed")
        if "missing api key" in err.lower():
            err = f"missing api key for provider: {provider}"
        return {
            "reasoning": "",
            "error": err,
            "status": result.get("status"),
            "input": perceived.get("normalized_input", {}),
            "memory": memory,
            "knowledge": rag_meta,
            "provider": provider,
            "model": model_name,
        }
    return {
        "reasoning": result.get("content", ""),
        "input": perceived.get("normalized_input", {}),
        "memory": memory,
        "knowledge": rag_meta,
        "provider": provider,
        "model": model_name,
        "llm_raw": result.get("raw"),
        "system_prompt": system_prompt,
        "_bench_platform_only": bool(use_platform_dispatch),
    }


def _cognition_sync(
    config: _facade().Dict[str, _facade().Any],
    perceived: _facade().Dict[str, _facade().Any],
    memory: _facade().Dict[str, _facade().Any],
    session,
    user_id: int,
    *,
    employee_id: str = "",
    task: str = "",
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    return _facade()._run_coro_sync(
        _facade()._cognition_real(
            config,
            perceived,
            memory,
            session,
            user_id,
            employee_id=employee_id,
            task=task,
            bench_llm_override=bench_llm_override,
        )
    )
