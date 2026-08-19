# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


@_facade().router.post("/employee-ai/draft", summary="6 阶段 AI 员工生成（SSE 流式）")
async def employee_ai_draft(
    body: _facade().EmployeeAiDraftBody,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """SSE 事件序列：stage_start / stage_progress / stage_done / stage_error / pipeline_done。

    ``pipeline_done`` 携带完整 manifest；客户端可在收到后离线编辑，再调 ``/api/mods/ai-scaffold``
    或 ``import_zip`` 落库上架（保持与现有 employee 工作台链路兼容）。
    """
    from modstore_server.employee_ai_pipeline import run_pipeline
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.script_agent.llm_client import RealLlmClient

    sf = _facade().get_session_factory()

    async def _stream():
        events: _facade().List[_facade().Dict[str, _facade().Any]] = []

        async def on_event(ev: _facade().Dict[str, _facade().Any]) -> None:
            events.append(ev)
            line = f"data: {_facade().json.dumps(ev, ensure_ascii=False)}\n\n"
            yield line.encode()

        with sf() as db:
            (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(
                db, user, body.provider, body.model
            )
            if err:
                err_ev = {"event": "pipeline_error", "stage": "init", "error": err}
                yield f"data: {_facade().json.dumps(err_ev, ensure_ascii=False)}\n\n".encode()
                return
            (api_key, _) = resolve_api_key(db, user.id, prov)
            if not api_key:
                err_ev = {
                    "event": "pipeline_error",
                    "stage": "init",
                    "error": "该供应商未配置可用 API Key",
                }
                yield f"data: {_facade().json.dumps(err_ev, ensure_ascii=False)}\n\n".encode()
                return
            base_url = (
                resolve_base_url(db, user.id, prov)
                if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                else None
            )
            llm = RealLlmClient(
                prov, api_key=api_key, model=mdl, base_url=base_url, forbid_reasoning_fallback=True
            )
            from modstore_server.models import Workflow as WorkflowModel

            wf_rows = (
                db.query(WorkflowModel)
                .filter(WorkflowModel.user_id == user.id, WorkflowModel.is_active.is_(True))
                .order_by(WorkflowModel.updated_at.desc())
                .limit(20)
                .all()
            )
            eligible_wfs = [
                {
                    "id": w.id,
                    "name": w.name or "",
                    "description": w.description or "",
                    "sandbox_passed": bool(getattr(w, "sandbox_passed_for_current_graph", False)),
                }
                for w in wf_rows
            ]

            async def _gen_wf_fallback() -> _facade().Dict[str, _facade().Any]:
                _pack_id = (body.suggested_id or "").strip() or None
                _pack_label = (body.brief[:40] if body.brief else "").strip() or _pack_id
                with sf() as db2:
                    return await _facade().generate_workflow_for_intent(
                        db2,
                        user,
                        role=body.brief[:40],
                        scenario=body.brief[:120],
                        workflow_name=f"AI 员工工作流 - {(body.suggested_id or body.brief[:16]).strip()}",
                        provider=prov,
                        model=mdl,
                        target_employee_pack_id=_pack_id,
                        target_employee_label=_pack_label,
                    )

            collected: _facade().List[_facade().Dict[str, _facade().Any]] = []

            async def on_event_gen(ev: _facade().Dict[str, _facade().Any]) -> None:
                collected.append(ev)

            import asyncio as _asyncio

            q: _facade().asyncio.Queue = _asyncio.Queue()

            async def _on_ev(ev: _facade().Dict[str, _facade().Any]) -> None:
                await q.put(ev)

            async def _run_and_sentinel() -> None:
                try:
                    await run_pipeline(
                        body.brief,
                        llm=llm,
                        on_event=_on_ev,
                        eligible_workflows=eligible_wfs,
                        generate_workflow_fallback=_gen_wf_fallback,
                    )
                finally:
                    await q.put(None)

            task = _asyncio.create_task(_run_and_sentinel())
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield f"data: {_facade().json.dumps(ev, ensure_ascii=False)}\n\n".encode()
            await task

    return _facade().StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@_facade().router.post("/employee-ai/refine-prompt", summary="LLM 优化 system prompt")
async def employee_ai_refine_prompt(
    body: _facade().EmployeeAiRefinePromptBody,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """用 LLM 重写 employee system prompt，返回优化后文本与一句话 diff 说明。"""
    from modstore_server.employee_ai_pipeline import refine_system_prompt
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.script_agent.llm_client import RealLlmClient

    sf = _facade().get_session_factory()
    with sf() as db:
        (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(
            db, user, body.provider, body.model
        )
        if err:
            raise _facade().HTTPException(400, err)
        (api_key, _) = resolve_api_key(db, user.id, prov)
        if not api_key:
            raise _facade().HTTPException(400, "该供应商未配置可用 API Key")
        base_url = (
            resolve_base_url(db, user.id, prov)
            if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
    llm = RealLlmClient(
        prov, api_key=api_key, model=mdl, base_url=base_url, forbid_reasoning_fallback=True
    )
    (result, err) = await refine_system_prompt(
        current_prompt=body.current_prompt,
        instruction=body.instruction,
        role_context=body.role_context,
        llm=llm,
    )
    if err or result is None:
        raise _facade().HTTPException(502, f"Prompt 优化失败: {err or '未知错误'}")
    return result


class EmployeeBenchRequest(_facade().BaseModel):
    employee_id: str = _facade().Field(..., description="员工包 ID（同 pack_id）")
    provider: _facade().Optional[str] = _facade().Field(None)
    model: _facade().Optional[str] = _facade().Field(None)
    per_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = _facade().Field(
        None,
        description="五维专属评分员工包映射 {维度键: employee_id}；有效键：manifest_compliance / declaration_completeness / api_testability_static / security_and_size / metadata_quality。合并优先级：环境变量 MODSTORE_AUDIT_DIM_* → LLM 自动从评审池挑选 → 本字段。未填满的维度可用服务端评审池（MODSTORE_BENCH_REVIEWER_POOL / *_FROM_CATALOG）自动补位。",
    )


class EmployeePublishRequest(_facade().BaseModel):
    employee_id: str = _facade().Field(..., description="员工包 ID（同 pack_id）")
    price: float = _facade().Field(0.0)
    industry: str = _facade().Field("通用", max_length=64)
    release_channel: str = _facade().Field("stable", max_length=32)


@_facade().router.post(
    "/employee-bench-test", summary="员工上架前基准测试（LLM 生成任务 + 执行 + 五维审核）"
)
async def employee_bench_test(
    body: EmployeeBenchRequest,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    1. LLM 生成 1-5 级（每级 3 条）共 15 项测试任务
    2. 逐条执行并记录 ok / cost_tokens / duration_ms
    3. 量化打分 + 五维审核
    4. 返回完整报告，前端据此决定是否允许上架
    """
    from modstore_server.employee_bench import generate_bench_tasks, run_and_score_bench

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    _facade().materialize_employee_pack_if_missing(employee_id)
    pack_dir = _facade().modstore_library_path() / employee_id
    brief = ""
    panel_summary = ""
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            mf = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
            brief = (
                str(mf.get("description") or "")
                or str(mf.get("identity", {}).get("description") or "")
            )[:800]
            rows = mf.get("workflow_employees") or []
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
        except Exception:
            pass
    sf = _facade().get_session_factory()
    with sf() as db:
        from modstore_server.services.llm import resolve_platform_bench_llm

        (prov, mdl) = resolve_platform_bench_llm()
        if not prov or not mdl:
            raise _facade().HTTPException(
                503,
                "基准测试需要平台 LLM 密钥（服务端环境变量），当前未配置。请联系运维设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL 及对应供应商的 API Key 环境变量。",
            )
        try:
            task_list = await generate_bench_tasks(
                brief or employee_id,
                panel_summary,
                db=db,
                user_id=user.id,
                provider=prov,
                model=mdl,
                use_platform_dispatch=True,
                strict=True,
            )
        except RuntimeError as exc:
            raise _facade().HTTPException(502, f"基准任务生成失败（LLM 调用）：{exc}") from exc
        report = await run_and_score_bench(
            employee_id,
            task_list,
            db=db,
            user=user,
            bench_llm_override=(prov, mdl),
            per_dimension_ids=body.per_dimension_ids,
        )
    return {"ok": True, "employee_id": employee_id, **report}


@_facade().router.post("/employee-publish", summary="员工包上架到商店目录")
async def employee_publish(
    body: EmployeePublishRequest,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    将本地库中的员工包重建 zip 并写入商店目录（catalog_store + catalog_items）。
    调用方应先通过 /employee-bench-test 且 passed=true，再调此接口。
    """
    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.models import CatalogItem

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    _facade().materialize_employee_pack_if_missing(employee_id)
    pack_dir = _facade().modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise _facade().HTTPException(404, f"员工包不存在: {employee_id}")
    try:
        raw_mf = _facade()._load_registry_aligned_employee_manifest(pack_dir, employee_id)
    except Exception as exc:
        raise _facade().HTTPException(500, f"manifest.json 读取失败: {exc}") from exc
    mf_path.write_text(
        _facade().json.dumps(raw_mf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        pkg_id = str(raw_mf.get("id") or employee_id).strip() or employee_id
        from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library

        zip_bytes = build_employee_pack_zip_for_library(pkg_id, raw_mf, pack_dir=pack_dir)
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise _facade().HTTPException(500, f"员工包打包失败: {exc}") from exc
    version = str(raw_mf.get("version") or "1.0.0").strip()
    rec = {
        "id": pkg_id,
        "name": str(raw_mf.get("name") or pkg_id),
        "version": version,
        "description": str(raw_mf.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry or str(raw_mf.get("industry") or "通用"),
        "release_channel": body.release_channel or "stable",
        "commerce": {"mode": "free" if body.price <= 0 else "paid", "price": body.price},
        "license": {"type": "personal", "verify_url": None},
    }
    import tempfile as _tmpmod

    with _tmpmod.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = _facade().Path(tmp.name)
    try:
        align_errs = package_manifest_alignment_errors(rec, tmp_path)
        if align_errs:
            raise _facade().HTTPException(
                400, "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs)
            )
        saved = append_package(rec, tmp_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise _facade().HTTPException(500, f"写入 catalog_store 失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    sf = _facade().get_session_factory()
    with sf() as db:
        try:
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=user.id)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
            if not row:
                row = CatalogItem(pkg_id=pkg_id, author_id=user.id)
                db.add(row)
            row.version = saved.get("version") or version
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = float(body.price)
            row.artifact = "employee_pack"
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            db.commit()
            try:
                from modstore_server.employee_asset_pipeline import (
                    mirror_catalog_file_to_market_files,
                )

                mirror_catalog_file_to_market_files(row.stored_filename)
            except Exception:
                pass
        except Exception as exc:
            db.rollback()
            raise _facade().HTTPException(500, f"写入数据库失败: {exc}") from exc
    return {
        "ok": True,
        "pkg_id": pkg_id,
        "version": saved.get("version") or version,
        "stored_filename": saved.get("stored_filename") or "",
        "name": saved.get("name") or rec["name"],
    }


class EmployeeSyncTestRequest(_facade().BaseModel):
    employee_id: str = _facade().Field(..., description="员工包 ID（同 pack_id）")
    fhd_base_url: _facade().Optional[str] = _facade().Field(
        None, description="宿主 fhd-sandbox-runtime 的 base URL，如 http://localhost:9999"
    )
    provider: _facade().Optional[str] = _facade().Field(None)
    model: _facade().Optional[str] = _facade().Field(None)
    price: float = _facade().Field(0.0)
    industry: str = _facade().Field("通用", max_length=64)
    per_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = _facade().Field(
        None,
        description="五维专属评分员工包映射 {维度键: employee_id}；与环境变量、自动评审池补位规则同 employee-bench-test。",
    )


@_facade().router.post("/employee-sync-test", summary="员工同步测试：bench→发布→推送到宿主安装")
async def employee_sync_test(
    body: EmployeeSyncTestRequest,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """
    一键同步流程：
    1. LLM 生成 1-5 级测试任务并执行 + 五维审核
    2. 通过后发布到 MODstore catalog（/v1/packages）
    3. 调用宿主 fhd-sandbox-runtime 的 /api/mod-store/install 安装此员工包
       → 员工出现在宿主「一键托管」面板、「员工工作流管理」页等位置
    """
    import httpx
    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_bench import generate_bench_tasks, run_and_score_bench
    from modstore_server.models import CatalogItem

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    _facade().materialize_employee_pack_if_missing(employee_id)
    pack_dir = _facade().modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise _facade().HTTPException(404, f"员工包不存在: {employee_id}")
    try:
        raw_mf = _facade()._load_registry_aligned_employee_manifest(pack_dir, employee_id)
    except Exception as exc:
        raise _facade().HTTPException(500, f"manifest.json 读取失败: {exc}") from exc
    brief = str(raw_mf.get("description") or "").strip()[:800]
    rows = raw_mf.get("workflow_employees") or []
    panel_summary = ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
    from modstore_server.services.llm import resolve_platform_bench_llm

    (prov, mdl) = resolve_platform_bench_llm()
    if not prov or not mdl:
        raise _facade().HTTPException(
            503,
            "同步测试需要平台 LLM 密钥（服务端环境变量），当前未配置。请联系运维设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL 及对应供应商的 API Key 环境变量。",
        )
    sf = _facade().get_session_factory()
    with sf() as db:
        try:
            task_list = await generate_bench_tasks(
                brief or employee_id,
                panel_summary,
                db=db,
                user_id=user.id,
                provider=prov,
                model=mdl,
                use_platform_dispatch=True,
                strict=True,
            )
        except RuntimeError as exc:
            raise _facade().HTTPException(502, f"基准任务生成失败（LLM 调用）：{exc}") from exc
        report = await run_and_score_bench(
            employee_id,
            task_list,
            db=db,
            user=user,
            bench_llm_override=(prov, mdl),
            per_dimension_ids=body.per_dimension_ids,
        )
    if not report.get("passed"):
        return {
            "ok": False,
            "stage": "bench_test",
            "reason": f"基准测试未通过（得分 {report.get('overall_score', 0):.1f}，需 ≥ 60）",
            "bench": report,
        }
    pkg_id = str(raw_mf.get("id") or employee_id).strip() or employee_id
    version = str(raw_mf.get("version") or "1.0.0").strip()
    try:
        from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library

        zip_bytes = build_employee_pack_zip_for_library(pkg_id, raw_mf, pack_dir=pack_dir)
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise _facade().HTTPException(500, f"员工包打包失败: {exc}") from exc
    rec = {
        "id": pkg_id,
        "name": str(raw_mf.get("name") or pkg_id),
        "version": version,
        "description": str(raw_mf.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry or str(raw_mf.get("industry") or "通用"),
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0.0},
        "license": {"type": "personal", "verify_url": None},
    }
    import tempfile as _tmpmod

    with _tmpmod.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path_str = tmp.name
    try:
        align_errs = package_manifest_alignment_errors(rec, _facade().Path(tmp_path_str))
        if align_errs:
            raise _facade().HTTPException(
                400, "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs)
            )
        saved = append_package(rec, _facade().Path(tmp_path_str))
    except Exception as exc:
        _facade().Path(tmp_path_str).unlink(missing_ok=True)
        raise _facade().HTTPException(500, f"写入 catalog_store 失败: {exc}") from exc
    finally:
        _facade().Path(tmp_path_str).unlink(missing_ok=True)
    sf2 = _facade().get_session_factory()
    with sf2() as db2:
        try:
            upsert_catalog_item_from_xc_package_dict(db2, saved, author_id=user.id)
            row = db2.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
            if not row:
                row = CatalogItem(pkg_id=pkg_id, author_id=user.id)
                db2.add(row)
            row.version = saved.get("version") or version
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            db2.commit()
        except Exception as exc:
            db2.rollback()
            raise _facade().HTTPException(500, f"写入数据库失败: {exc}") from exc
    fhd_base = (body.fhd_base_url or "").strip().rstrip("/")
    fhd_result: _facade().Dict[str, _facade().Any] = {
        "skipped": True,
        "reason": "未提供 fhd_base_url",
    }
    if fhd_base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{fhd_base}/api/mod-store/install",
                    json={
                        "pkg_id": pkg_id,
                        "version": saved.get("version") or version,
                        "activate": True,
                    },
                )
            if r.status_code < 400:
                fhd_result = {"ok": True, "status": r.status_code, "data": r.json()}
            else:
                fhd_result = {"ok": False, "status": r.status_code, "error": r.text[:400]}
        except Exception as exc:
            fhd_result = {"ok": False, "error": str(exc)[:400]}
    return {
        "ok": True,
        "stage": "synced",
        "pkg_id": pkg_id,
        "version": saved.get("version") or version,
        "bench": report,
        "catalog": {"ok": True, "stored_filename": saved.get("stored_filename") or ""},
        "fhd_install": fhd_result,
    }


class EmployeeSaveBody(_facade().BaseModel):
    manifest: _facade().Dict[str, _facade().Any] = _facade().Field(
        ..., description="员工完整 manifest（employee_config_v2 结构）"
    )
    employee_id: _facade().Optional[str] = _facade().Field(
        None, max_length=128, description="已有员工ID；为空时从 manifest.identity.id 读取"
    )
    provider: _facade().Optional[str] = _facade().Field(
        None,
        max_length=64,
        description="注册 vibe-coding Skill 用的 LLM 供应商（为空则尝试用户默认）",
    )
    model: _facade().Optional[str] = _facade().Field(
        None, max_length=128, description="注册 vibe-coding Skill 用的 LLM 模型"
    )
    register_skills: bool = _facade().Field(
        True, description="是否同时注册 vibe-coding ESkill（需要 LLM；失败不影响保存）"
    )
