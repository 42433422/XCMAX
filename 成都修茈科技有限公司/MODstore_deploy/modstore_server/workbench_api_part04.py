# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib
from typing import Literal


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


@_facade().router.post("/web-search", summary="工作台 · 联网检索网页摘要（供直接对话）")
async def workbench_web_search(
    body: _facade().WorkbenchWebSearchBody,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """与 Agent `internet_search` 同源：Bing 爬虫 → Tavily → DDG/SearXNG，并抓取结果页正文。"""
    out = await _facade().fetch_web_search_context_pack(
        query=body.query,
        user_id=int(user.id),
        max_results=body.max_results,
        max_chars=body.max_chars,
    )
    if out.get("error") == "rate_limited":
        raise _facade().HTTPException(429, (out.get("warnings") or ["今日联网检索次数已达上限"])[0])
    return out


@_facade().router.post("/research-context", summary="联网检索摘要 + GitHub 公开资料（供需求规划）")
async def workbench_research_context(
    body: _facade().WorkbenchResearchBody,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    优先 Bing HTML 爬虫检索网页摘要，失败时用 Tavily 兜底（不抓取任意第三方 URL），
    并从结果与用户 brief 中解析 github.com 仓库，仅通过 api.github.com 拉取公开元数据与 README，
    拼成有上限的 context_pack。
    """
    out = await _facade().build_research_context(
        brief=body.brief,
        intent=body.intent,
        max_repos=body.max_repos,
        max_chars=body.max_chars,
        max_web=body.max_web,
        user_id=user.id,
    )
    if out.get("ok") is False and out.get("error") == "rate_limited":
        raise _facade().HTTPException(429, out.get("warnings", ["请求过于频繁"])[0])
    return out


@_facade().router.post("/sessions", summary="启动工作台 AI 编排（异步）")
async def create_workbench_session(
    request: _facade().Request,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    raw_files: _facade().List[_facade().Dict[str, _facade().Any]] = []
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        form = await request.form()
        meta_raw = str(form.get("metadata") or "{}")
        try:
            meta = _facade().json.loads(meta_raw)
        except _facade().json.JSONDecodeError as e:
            raise _facade().HTTPException(400, "metadata 必须是 JSON") from e
        if not isinstance(meta, dict):
            raise _facade().HTTPException(400, "metadata 必须是 JSON 对象")
        body = _facade()._parse_workbench_session_create(meta)
        uploads = [
            v
            for (_, v) in form.multi_items()
            if hasattr(v, "filename") and callable(getattr(v, "read", None))
        ]
        raw_files = await _facade()._read_workbench_uploads(uploads)
    else:
        try:
            meta = await request.json()
        except Exception as e:
            raise _facade().HTTPException(400, "请求体必须是 JSON 对象") from e
        if not isinstance(meta, dict):
            raise _facade().HTTPException(400, "请求体必须是 JSON 对象")
        body = _facade()._parse_workbench_session_create(meta)
    payload = body.model_dump()
    if raw_files:
        payload["_files"] = raw_files
    return await _facade().start_workbench_session_for_user(int(user.id), payload)


@_facade().router.post("/script-sessions", summary="启动 AI + Python 文件处理任务")
async def create_workbench_script_session(
    metadata: str = _facade().Form(...),
    files: _facade().List[_facade().UploadFile] = _facade().File(default=[]),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    try:
        meta = _facade().json.loads(metadata or "{}")
    except _facade().json.JSONDecodeError as e:
        raise _facade().HTTPException(400, "metadata 必须是 JSON") from e
    brief = str(meta.get("brief") or "").strip()
    if len(brief) < 3:
        raise _facade().HTTPException(400, "brief 不能为空")
    raw_files: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for f in files or []:
        content = await f.read()
        if len(content) > 30 * 1024 * 1024:
            raise _facade().HTTPException(400, f"文件过大: {f.filename}")
        raw_files.append({"filename": f.filename or "upload.bin", "content": content})
    if not raw_files:
        raise _facade().HTTPException(400, "请上传至少一个文件")
    sid = _facade().uuid.uuid4().hex[:24]
    payload = {
        "intent": _facade().CANVAS_SKILL_INTENT,
        "execution_mode": "script",
        "brief": brief,
        "workflow_name": meta.get("workflow_name"),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "_files": raw_files,
    }
    async with _facade()._SESSION_LOCK:
        _facade().WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": _facade().CANVAS_SKILL_INTENT,
            "status": "running",
            "steps": _facade()._default_steps(_facade().CANVAS_SKILL_INTENT, "script"),
            "planning_record": _facade()._planning_record(payload),
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _facade()._persist_workbench_session_unlocked(sid)
    _script_task = _facade().asyncio.create_task(_facade()._run_pipeline(sid, user.id, payload))
    _script_task.add_done_callback(_facade()._pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running"}


@_facade().router.get("/sessions/{session_id}", summary="查询编排会话（轮询）")
async def get_workbench_session(
    session_id: str, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    payload = await _facade().get_workbench_session_snapshot(session_id, int(user.id))
    if payload is None:
        async with _facade()._SESSION_LOCK:
            _facade()._hydrate_workbench_session_unlocked(session_id)
            exists = _facade().WORKBENCH_SESSIONS.get(session_id)
        if not exists:
            raise _facade().HTTPException(404, "会话不存在或已过期")
        raise _facade().HTTPException(403, "无权访问此会话")
    return payload


@_facade().router.get("/sessions/{session_id}/files/{filename}", summary="下载脚本执行结果文件")
async def download_workbench_session_file(
    session_id: str,
    filename: str,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(session_id)
        sess = _facade().WORKBENCH_SESSIONS.get(session_id)
    if not sess:
        raise _facade().HTTPException(404, "会话不存在或已过期")
    if sess.get("user_id") != user.id:
        raise _facade().HTTPException(403, "无权访问此会话")
    result = sess.get("script_result") or {}
    for o in result.get("outputs") or []:
        if o.get("filename") == filename:
            path = _facade().Path(str(o.get("path") or ""))
            if path.is_file():
                return _facade().FileResponse(path, filename=filename)
    raise _facade().HTTPException(404, "文件不存在")


@_facade().router.post("/sessions/{session_id}/retry", summary="重试编排会话")
async def retry_workbench_session(
    session_id: str, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(session_id)
        old = _facade().WORKBENCH_SESSIONS.get(session_id)
    if not old:
        raise _facade().HTTPException(404, "会话不存在或已过期")
    if old.get("user_id") != user.id:
        raise _facade().HTTPException(403, "无权访问此会话")
    checkpoint = old.get("_pipeline_checkpoint") or {}
    failed_step = checkpoint.get("failed_step")
    can_resume = bool(failed_step and checkpoint.get("res") and checkpoint.get("pack_dir"))
    if can_resume:
        new_sid = _facade().uuid.uuid4().hex[:24]
        steps = _facade()._default_steps(
            old.get("intent", "employee"),
            old.get("planning_record", {}).get("execution_mode") or "employee",
            employee_target=str(checkpoint.get("employee_target") or "pack_plus_workflow"),
        )
        _step_order = [s["id"] for s in steps]
        if failed_step in _step_order:
            for s in steps:
                if _step_order.index(s["id"]) < _step_order.index(failed_step):
                    s["status"] = "done"
                    s["message"] = "已完成（重试复用）"
        async with _facade()._SESSION_LOCK:
            _facade().WORKBENCH_SESSIONS[new_sid] = {
                "id": new_sid,
                "user_id": user.id,
                "intent": old.get("intent", "employee"),
                "status": "running",
                "steps": steps,
                "planning_record": dict(old.get("planning_record") or {}),
                "artifact": None,
                "error": None,
                "validate_warnings": None,
                "sandbox_report": None,
                "script_result": None,
                "_resume_checkpoint": checkpoint,
            }
            _facade()._persist_workbench_session_unlocked(new_sid)
        _task = _facade().asyncio.create_task(
            _facade()._run_pipeline(new_sid, user.id, old.get("planning_record") or {})
        )
        _task.add_done_callback(_facade()._pipeline_task_failsafe(new_sid))
        return {"session_id": new_sid, "status": "running", "resumed_from": failed_step}
    new_sid = _facade().uuid.uuid4().hex[:24]
    payload = old.get("planning_record") or {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("intent", old.get("intent", "employee"))
    payload.setdefault("brief", "")
    payload.setdefault("replace", True)
    async with _facade()._SESSION_LOCK:
        _facade().WORKBENCH_SESSIONS[new_sid] = {
            "id": new_sid,
            "user_id": user.id,
            "intent": payload.get("intent") or old.get("intent", "employee"),
            "status": "running",
            "steps": _facade()._default_steps(
                payload.get("intent") or old.get("intent", "employee"),
                payload.get("execution_mode") or "employee",
                employee_target=str(payload.get("employee_target") or "pack_plus_workflow"),
            ),
            "planning_record": dict(payload),
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _facade()._persist_workbench_session_unlocked(new_sid)
    _task = _facade().asyncio.create_task(_facade()._run_pipeline(new_sid, user.id, payload))
    _task.add_done_callback(_facade()._pipeline_task_failsafe(new_sid))
    return {"session_id": new_sid, "status": "running"}


class WorkbenchEdgeTtsBody(_facade().BaseModel):
    """与 Edge 浏览器「大声朗读」相同的在线神经语音（经 edge-tts 访问微软语音服务）。"""

    text: str = _facade().Field(..., min_length=1, max_length=5000)
    voice: str = _facade().Field("zh-CN-XiaoxiaoNeural", max_length=120)
    rate: float = _facade().Field(
        1.0, ge=0.6, le=1.6, description="相对语速，约映射到 Edge 的 rate 百分比"
    )


class WorkbenchUnifiedTtsBody(_facade().BaseModel):
    """统一 TTS：优先 MiMo，失败回退 Edge 神经音。"""

    text: str = _facade().Field(..., min_length=1, max_length=5000)
    voice: str = _facade().Field("", max_length=120, description="MiMo 音色（如 冰糖）；空则用默认")
    edge_voice: str = _facade().Field("zh-CN-XiaoxiaoNeural", max_length=120)
    rate: float = _facade().Field(1.0, ge=0.6, le=1.6)


class WorkbenchVibeCodeSkillBody(_facade().BaseModel):
    """工作台「AI 代码技能」: NL → vibe-coding CodeSkill → 试跑 → 可选发布。"""

    brief: str = _facade().Field(..., min_length=3, max_length=8000)
    run_input: _facade().Dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    skill_id: _facade().Optional[str] = _facade().Field(None, max_length=128)
    mode: Literal["brief_first", "direct"] = "brief_first"
    dry_run: bool = _facade().Field(False, description="为 True 时只生成代码 + 试跑,不上架")
    provider: _facade().Optional[str] = _facade().Field(None, max_length=64)
    model: _facade().Optional[str] = _facade().Field(None, max_length=128)
    project_root: _facade().Optional[str] = _facade().Field(
        None,
        max_length=4096,
        description="可选：项目根目录（必须在用户工作区内）。非空时会先做目录扫描/技术栈分析并注入 brief，并把 project_analysis 自动加入 run_input，用于文档生成器/项目分析类 Skill。",
    )
    publish: _facade().Optional[_facade().Dict[str, _facade().Any]] = _facade().Field(
        None, description="非空时在试跑通过后调 SkillPublisher 上架到本 MODstore"
    )


@_facade().router.post("/vibe-code-skill", summary="vibe-coding NL → CodeSkill 全闭环")
async def workbench_vibe_code_skill(
    body: WorkbenchVibeCodeSkillBody,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """vibe-coding 端到端 API:生成代码、试跑、可选直接上架本 MODstore。

    本接口同步返回(单次代码生成大约 5-30 秒,取决于 LLM 速度);
    长时间任务请用「脚本工作流」。
    """
    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto

    sf = _facade().get_session_factory()
    with sf() as db:
        (prov, mdl, err) = await resolve_llm_provider_model_auto(
            db, user, body.provider, body.model
        )
        if err:
            raise _facade().HTTPException(400, err)

    def _do() -> _facade().Dict[str, _facade().Any]:
        try:
            from modstore_server.integrations.vibe_adapter import (
                VibeIntegrationError,
                VibePathError,
                ensure_within_workspace,
                get_vibe_coder,
            )
        except ImportError as exc:
            return {"ok": False, "error": f"未启用 vibe-coding 集成: {exc}"}
        resolved_project_root: _facade().Optional[str] = None
        if body.project_root and body.project_root.strip():
            try:
                resolved_project_root = str(
                    ensure_within_workspace(body.project_root.strip(), user_id=int(user.id or 0))
                )
            except VibePathError as exc:
                return {"ok": False, "error": f"project_root 路径无效: {exc}"}
            except Exception as exc:
                return {"ok": False, "error": f"project_root 校验失败: {exc}"}
        sf2 = _facade().get_session_factory()
        with sf2() as session:
            try:
                coder = get_vibe_coder(
                    session=session, user_id=int(user.id or 0), provider=prov, model=mdl
                )
            except VibeIntegrationError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                skill = coder.code(
                    body.brief.strip(),
                    mode=body.mode,
                    skill_id=body.skill_id or None,
                    project_root=resolved_project_root,
                )
            except Exception as exc:
                return {"ok": False, "error": f"vibe-coding 生成失败: {exc}"}
            run_input_final = dict(body.run_input or {})
            if resolved_project_root and "project_analysis" not in run_input_final:
                try:
                    import json as _json
                    from vibe_coding.code_factory import analyze_project

                    analysis = analyze_project(resolved_project_root)
                    run_input_final["project_analysis"] = _json.loads(
                        _json.dumps(
                            {
                                "root_name": analysis.root_name,
                                "manifests": analysis.manifests,
                                "top_level": analysis.top_level,
                                "languages": analysis.languages,
                                "tech_stack": analysis.tech_stack,
                                "entry_points": analysis.entry_points,
                                "config_files": analysis.config_files,
                                "readme_snippet": analysis.readme_snippet,
                                "git_info": analysis.git_info,
                            },
                            ensure_ascii=False,
                        )
                    )
                except Exception:
                    pass
            sid = getattr(skill, "skill_id", "") or ""
            run_dict: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
            try:
                run_obj = coder.run(sid, run_input_final)
                run_dict = (
                    run_obj.to_dict()
                    if hasattr(run_obj, "to_dict") and callable(run_obj.to_dict)
                    else {"output": getattr(run_obj, "output", None)}
                )
            except Exception as exc:
                run_dict = {"ok": False, "error": f"试跑失败: {exc}"}
            skill_dict: _facade().Dict[str, _facade().Any]
            if hasattr(skill, "to_dict") and callable(skill.to_dict):
                skill_dict = dict(skill.to_dict())
            else:
                skill_dict = {"skill_id": sid, "code": getattr(skill, "code", "") or ""}
            publish_dict: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
            if body.publish and (not body.dry_run):
                publish_dict = _facade()._publish_vibe_skill_via_local_modstore(
                    coder, sid, body.publish, user_id=int(user.id or 0)
                )
            return {
                "ok": True,
                "provider": prov,
                "model": mdl,
                "skill": skill_dict,
                "run": run_dict,
                "publish": publish_dict,
                "project_root_used": resolved_project_root,
            }

    out = await _facade().asyncio.to_thread(_do)
    return out


def _publish_vibe_skill_via_local_modstore(
    coder: _facade().Any,
    skill_id: str,
    publish_cfg: _facade().Dict[str, _facade().Any],
    *,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    """直接调本 MODstore 的 catalog 上传接口,不用 HTTP 自调来回。

    用 vibe-coding 的 ``SkillPackager`` 打包(它知道 .xcmod 内部结构),
    再走 :func:`catalog_store.append_package` + ``CatalogItem`` 写库。
    """
    try:
        from vibe_coding.agent.marketplace import PublishOptions, SkillPackager
    except ImportError as exc:
        return {"ok": False, "error": f"vibe-coding marketplace 未安装: {exc}"}
    pkg_id = str(publish_cfg.get("pkg_id") or "").strip()
    if not pkg_id:
        return {"ok": False, "error": "publish.pkg_id 必填"}
    artifact_kind = str(publish_cfg.get("artifact") or "mod").strip() or "mod"
    if artifact_kind not in ("mod", "employee_pack"):
        return {"ok": False, "error": f"不支持的 artifact: {artifact_kind}"}
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    risk_decision = evaluate_risk(
        "mod_auto_publish",
        {
            "human_approved": True,
            "approved_by": f"workbench-user:{user_id}",
            "trigger": "explicit_workbench_publish",
        },
        action_id=f"mod-publish:{user_id}:{pkg_id}:{str(publish_cfg.get('version') or '1.0.0')}",
        source="workbench.vibe_code_publish",
    )
    if not risk_decision.allowed:
        return {
            "ok": False,
            "error": "autonomy_guard blocked publish",
            "risk_decision": risk_decision.to_dict(),
        }
    try:
        skill = coder.code_store.get_code_skill(skill_id)
    except KeyError:
        return {"ok": False, "error": f"skill_id 不存在: {skill_id}"}
    options = PublishOptions(
        pkg_id=pkg_id,
        version=str(publish_cfg.get("version") or "1.0.0"),
        name=str(publish_cfg.get("name") or pkg_id),
        description=str(publish_cfg.get("description") or ""),
        price=float(publish_cfg.get("price") or 0.0),
        artifact=artifact_kind,
        industry=str(publish_cfg.get("industry") or "通用"),
        author=f"user-{user_id}",
    )
    try:
        packager = SkillPackager()
        artifact = packager.package_skill(skill, options=options)
    except Exception as exc:
        return {"ok": False, "error": f"打包失败: {exc}"}
    try:
        from modstore_server.catalog_store import append_package
        from modstore_server.models import CatalogItem

        rec = {
            "id": pkg_id,
            "name": options.name,
            "version": options.version,
            "description": options.description,
            "artifact": artifact_kind,
            "industry": options.industry,
            "release_channel": "stable",
            "commerce": {"mode": "free" if options.price <= 0 else "paid", "price": options.price},
            "license": {"type": "personal", "verify_url": None},
        }
        sf3 = _facade().get_session_factory()
        with sf3() as session:
            saved = append_package(rec, _facade().Path(artifact.archive_path))
            row = session.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
            if not row:
                row = CatalogItem(pkg_id=pkg_id, author_id=user_id)
                session.add(row)
            row.version = saved.get("version") or rec["version"]
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = float(options.price)
            row.artifact = artifact_kind
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            session.commit()
            if artifact_kind == "employee_pack":
                try:
                    from modstore_server.employee_asset_pipeline import (
                        mirror_catalog_file_to_market_files,
                    )

                    mirror_catalog_file_to_market_files(row.stored_filename)
                except Exception:
                    pass
    except Exception as exc:
        return {
            "ok": False,
            "error": f"上架到本地 MODstore 失败: {exc}",
            "artifact": getattr(artifact, "to_dict", lambda: {})(),
        }
    return {
        "ok": True,
        "pkg_id": pkg_id,
        "version": options.version,
        "artifact": getattr(artifact, "to_dict", lambda: {})(),
    }


def _edge_tts_rate_str(rate: float) -> str:
    from modstore_server.edge_tts_service import rate_str_from_float

    return rate_str_from_float(rate)


async def _edge_tts_stream_chunks(text: str, voice: str, rate_str: str):
    from modstore_server.edge_tts_service import stream_audio

    async for data in stream_audio(text, voice, rate_str):
        yield data


@_facade().router.post("/tts", summary="统一 TTS（MiMo → Edge 神经音，返回完整音频）")
async def workbench_unified_tts(
    body: WorkbenchUnifiedTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """优先小米 MiMo-V2.5 TTS，失败回退 edge-tts；不提供浏览器系统 TTS。"""
    from fastapi.responses import Response

    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    try:
        from modstore_server.mimo_tts_service import DEFAULT_VOICE as MIMO_VOICE
        from modstore_server.mimo_tts_service import synthesize_mimo_tts_async

        mimo_voice = (body.voice or "").strip() or MIMO_VOICE
        (audio, err, meta) = await synthesize_mimo_tts_async(text, voice=mimo_voice)
        if audio and (not err):
            mime = str(meta.get("mime") or "audio/wav")
            return Response(
                content=audio,
                media_type=mime,
                headers={
                    "Cache-Control": "no-cache",
                    "X-TTS-Provider": "mimo",
                    "X-TTS-Voice": str(meta.get("voice") or mimo_voice),
                },
            )
    except Exception:
        pass
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503, "MiMo 与 edge-tts 均不可用。请配置 MIMO_API_KEY 或 pip install edge-tts"
        )
    edge_voice = (body.edge_voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        chunks: list[bytes] = []
        async for data in _facade()._edge_tts_stream_chunks(text, edge_voice, rate_str):
            if data:
                chunks.append(data)
        mp3 = b"".join(chunks)
        if not mp3:
            raise RuntimeError("edge-tts empty")
        return Response(
            content=mp3,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "edge",
                "X-TTS-Voice": edge_voice,
            },
        )
    except _facade().HTTPException:
        raise
    except Exception as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc


@_facade().router.post("/tts/edge", summary="微软在线神经 TTS（edge-tts，返回 MP3）")
async def workbench_edge_tts(
    body: WorkbenchEdgeTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        return _facade().StreamingResponse(
            _facade()._edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except _facade().HTTPException:
        raise
    except Exception as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc


@_facade().router.post("/tts/edge/stream", summary="微软在线神经 TTS（edge-tts，chunked MP3 流）")
async def workbench_edge_tts_stream(
    body: WorkbenchEdgeTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        return _facade().StreamingResponse(
            _facade()._edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except _facade().HTTPException:
        raise
    except Exception as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc
