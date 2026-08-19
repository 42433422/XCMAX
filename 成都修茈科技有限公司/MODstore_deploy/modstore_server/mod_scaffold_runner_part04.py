# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


async def run_mod_suite_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    replace: bool = True,
    industry_id: _facade().Optional[str] = None,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    generate_frontend: bool = True,
    enable_vibe_heal: bool = True,
    manifest_override: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """
    文档/需求驱动的一体化 Mod 生成：manifest + ai_blueprint + 员工路由骨架，
    并为每个员工创建工作流后回写 workflow_id。

    ``generate_frontend`` 之前是 NameError 导致仓库页 AI 脚手架直接挂；现在补默认。
    ``enable_vibe_heal`` 控制是否在导入后调用 vibe-coding 的 ``heal_project`` 自愈一轮。
    ``manifest_override`` 当前端已通过 AI 流水线生成完整 manifest 时直接传入，
    跳过蓝图生成阶段，避免用户编辑被覆盖。
    """
    if manifest_override and isinstance(manifest_override, dict):
        gen: _facade().Dict[str, _facade().Any] = {"ok": True, "parsed": manifest_override}
    else:
        gen = await _facade().generate_mod_suite_blueprint_async(
            db, user, brief=brief, suggested_id=suggested_id, provider=provider, model=model
        )
    if not gen.get("ok"):
        return gen
    imported = _facade().import_mod_suite_repository(
        db, user, parsed=gen["parsed"], replace=replace, generate_frontend=generate_frontend
    )
    if not imported.get("ok"):
        return imported
    dest = _facade().Path(imported["path"])
    manifest = imported["manifest"]
    employees = imported.get("employees") or []
    blueprint = imported.get("blueprint") or {}
    industry_card = _facade().write_mod_suite_industry_card(dest, blueprint)
    ui_shell = _facade().write_mod_suite_ui_shell(dest, blueprint)
    wf = await _facade().create_mod_suite_workflows_async(
        db,
        user,
        mod_dir=dest,
        employees=employees,
        brief=brief,
        provider=gen.get("provider"),
        model=gen.get("model"),
    )
    workflow_results = wf.get("workflow_results") or []
    workflow_sandbox = _facade().run_mod_suite_workflow_sandboxes(db, user, workflow_results)
    api_summary = {"nodes": wf.get("api_nodes") or [], "warnings": wf.get("api_warnings") or []}
    employee_readiness = _facade().analyze_mod_employee_readiness(db, user, dest)
    pack_registration: _facade().Dict[str, _facade().Any] = {"registered": [], "errors": []}
    if employees:
        try:
            pack_registration = await _facade().register_mod_employee_packs_async(
                db,
                user,
                mod_dir=dest,
                workflow_results=workflow_results,
                industry=str(manifest.get("industry") or "通用"),
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "register_mod_employee_packs_async failed in ai-scaffold"
            )
    graph_patch_result = _facade().patch_workflow_graph_employee_nodes(
        db, user, mod_dir=dest, workflow_results=workflow_results
    )
    vibe_index_summary = (
        await _facade().asyncio.to_thread(
            _facade()._index_mod_with_vibe,
            db,
            user,
            mod_dir=dest,
            provider=gen.get("provider") or "",
            model=gen.get("model") or "",
        )
        if enable_vibe_heal
        else {"enabled": False}
    )
    _facade().write_mod_suite_blueprint(
        dest,
        blueprint,
        workflow_results,
        industry_card=industry_card,
        ui_shell=ui_shell,
        api_summary=api_summary,
        workflow_sandbox=workflow_sandbox,
        employee_readiness=employee_readiness,
        vibe_index=vibe_index_summary,
    )
    chosen_industry = str(industry_id or "").strip()
    if chosen_industry and chosen_industry != "通用":
        try:
            from modman.industry_presets import apply_industry_to_mod_dir
            from modman.manifest_util import read_manifest as _read_manifest

            apply_industry_to_mod_dir(dest, chosen_industry)
            (data, err) = _read_manifest(dest)
            if not err and data:
                manifest = data
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "apply_industry_to_mod_dir failed for %s", chosen_industry
            )
    mod_sandbox = _facade().run_mod_suite_mod_sandbox(dest, workflow_results)
    validation_summary = _facade()._suite_validation_summary(dest, workflow_results)
    validation_summary["mod_sandbox"] = mod_sandbox
    validation_summary["api_warnings"] = api_summary["warnings"]
    validation_summary["employee_readiness"] = employee_readiness
    validation_summary["vibe_index"] = vibe_index_summary
    validation_summary["pack_registration"] = pack_registration
    (data, err) = (None, None)
    try:
        from modman.manifest_util import read_manifest

        (data, err) = read_manifest(dest)
    except Exception:
        (data, err) = (None, None)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": data or manifest,
        "workflow_results": workflow_results,
        "blueprint": blueprint,
        "industry_card": industry_card,
        "ui_shell": ui_shell,
        "api_summary": api_summary,
        "workflow_sandbox": workflow_sandbox,
        "employee_readiness": employee_readiness,
        "graph_patch": graph_patch_result,
        "mod_sandbox": mod_sandbox,
        "validation_summary": validation_summary,
        "vibe_index": vibe_index_summary,
    }


def _index_mod_with_vibe(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    provider: str,
    model: str,
) -> _facade().Dict[str, _facade().Any]:
    """同步辅助:用 vibe-coding 的 ``ProjectVibeCoder.index_project`` 缓存索引。

    任何失败都视为可降级,只把 reason 留在返回值,不阻塞 Mod 流水线。
    """
    if not provider or not model:
        return {"enabled": False, "reason": "缺少 provider/model,跳过 vibe 索引"}
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_project_vibe_coder,
        )
    except ImportError as exc:
        return {"enabled": False, "reason": f"integrations 未导入: {exc}"}
    try:
        coder = get_project_vibe_coder(
            mod_dir, session=db, user_id=user.id, provider=provider, model=model
        )
    except VibeIntegrationError as exc:
        return {"enabled": False, "reason": str(exc)}
    except Exception as exc:
        return {"enabled": False, "reason": f"vibe coder 构造失败: {exc}"}
    try:
        idx = coder.index_project(refresh=True)
    except Exception as exc:
        return {"enabled": True, "ok": False, "reason": f"index_project 失败: {exc}"}
    summary: _facade().Dict[str, _facade().Any] = {"enabled": True, "ok": True}
    try:
        if hasattr(idx, "summary") and callable(idx.summary):
            summary["summary"] = idx.summary()
        else:
            summary["summary"] = {
                "files": getattr(idx, "files_count", None) or len(getattr(idx, "files", []) or [])
            }
    except Exception as exc:
        summary["summary"] = {"error": f"index summary 取数失败: {exc}"}
    return summary


async def attach_nl_workflow_to_employee_pack_dir(
    db: _facade().Session,
    user: _facade().User,
    *,
    pack_dir: _facade().Path,
    brief: str,
    workflow_name: _facade().Optional[str],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    status_hook: _facade().Optional[_facade().Callable[..., _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """在已落盘的员工包目录上创建画布工作流、NL 生图，并把 ``workflow_id`` 写回 manifest。

    改进：在调用 apply_nl_workflow_graph 之前，先把员工包 .py 注册为真实可执行 ESkill，
    生成的 preset_eskill_nodes 传给 NL 图生成器，画布节点将直接引用真脚本 Skill。
    若注册失败（vibe-coding 未安装/无脚本），自动退化为旧行为。
    """
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    name = ((workflow_name or "").strip() or f"员工包工作流 {pack_dir.name}")[:256]
    panel_summary = ""
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            _mf_raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
            rows = _mf_raw.get("workflow_employees")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                panel_summary = str(rows[0].get("panel_summary") or "").strip()
        except Exception:
            pass
    eskill_specs: list[dict] = []
    try:
        from modstore_server.employee_skill_register import register_employee_pack_as_eskills

        eskill_specs = await register_employee_pack_as_eskills(
            db,
            user,
            pack_dir=pack_dir,
            brief=(brief or "").strip(),
            panel_summary=panel_summary,
            provider=provider,
            model=model,
            status_hook=status_hook,
        )
    except Exception as exc:
        _facade().logger.warning("员工 Skill 注册失败，退化为旧 NL 图行为: %s", exc)
    wf = _facade().Workflow(
        user_id=user.id,
        name=name,
        description=(brief or "").strip()[:4000] or "由工作台「做员工」生成的单员工工作流",
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    target_pack_id = pack_dir.name
    target_label = pack_dir.name
    try:
        mf_for_target = (
            _facade().json.loads(mf_path.read_text(encoding="utf-8")) if mf_path.is_file() else {}
        )
        target_pack_id = str(mf_for_target.get("id") or pack_dir.name).strip() or pack_dir.name
        emp_obj = (
            mf_for_target.get("employee") if isinstance(mf_for_target.get("employee"), dict) else {}
        )
        target_label = (
            str(emp_obj.get("label") or mf_for_target.get("name") or target_pack_id).strip()
            or target_pack_id
        )
    except Exception:
        pass
    nl = await apply_nl_workflow_graph(
        db,
        user,
        workflow_id=wf.id,
        brief=(brief or "单员工任务流").strip(),
        provider=provider,
        model=model,
        status_hook=status_hook,
        preset_eskill_nodes=eskill_specs or None,
        target_employee_pack_id=target_pack_id,
        target_employee_label=target_label,
    )
    fallback_graph = _facade()._ensure_minimal_employee_workflow_graph(
        db,
        wf.id,
        employee_id=target_pack_id,
        employee_label=target_label,
        task=brief or "根据工作流输入完成员工任务",
    )
    mf = pack_dir / "manifest.json"
    if not mf.is_file():
        return {"ok": False, "error": "manifest.json 缺失", "workflow_id": wf.id}
    try:
        raw = _facade().json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e), "workflow_id": wf.id}
    rows = raw.get("workflow_employees")
    panel_summary = panel_summary or ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        rows[0] = {**rows[0], "workflow_id": wf.id}
        panel_summary = panel_summary or str(rows[0].get("panel_summary") or "").strip()
        raw["workflow_employees"] = rows
    v2 = raw.get("employee_config_v2")
    if isinstance(v2, dict):
        collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
        workflow = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
        workflow = {**workflow, "workflow_id": wf.id}
        v2["collaboration"] = {**collab, "workflow": workflow}
        cognition = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
        agent = cognition.get("agent") if isinstance(cognition.get("agent"), dict) else {}
        if panel_summary and (not str(agent.get("system_prompt") or "").strip()):
            agent = {**agent, "system_prompt": panel_summary}
            cognition = {**cognition, "agent": agent}
            v2["cognition"] = cognition
        raw["employee_config_v2"] = v2
    raw["workflow_attachment"] = {
        "workflow_id": wf.id,
        "nl_graph_ok": bool(nl.get("ok")),
        "nodes_created": int(nl.get("nodes_created") or 0),
        "fallback_graph": fallback_graph,
        "eskills": [
            {"eskill_id": s["eskill_id"], "name": s["name"], "vibe_skill_id": s["vibe_skill_id"]}
            for s in eskill_specs
        ],
    }
    try:
        from modstore_server.employee_pack_workflow_bundle import embed_workflow_bundles_in_manifest

        embed_workflow_bundles_in_manifest(db, raw)
    except Exception as _bundle_exc:
        _facade().logger.warning(
            "attach_nl_workflow: embed bundles failed wf_id=%d: %s", wf.id, _bundle_exc
        )
    mf.write_text(_facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest

        reconcile_employee_pack_manifest(pack_dir, brief=(brief or "").strip())
    except Exception as _rec_exc:
        _facade().logger.warning("attach_nl_workflow: manifest reconcile failed: %s", _rec_exc)
    return {
        "ok": True,
        "automation_complete": True,
        "workflow_id": wf.id,
        "nl": nl,
        "eskill_count": len(eskill_specs),
    }


async def run_employee_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    publish_to_catalog: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """
    生成 employee_pack 并导入用户库。商店执行器仍读 CatalogItem；此处产物用于本地库与「员工制作」页继续上架。

    :param publish_to_catalog: 默认 True，保持向后兼容（CLI / 旧脚手架直接调用时仍会写 ``packages.json``
        与 ``catalog_items``）。工作台「做员工」流水线会传 False，仅在 ``library/<pid>`` 落本地工作目录，
        让用户在 ModAuthoring / 员工编辑器里检查后再点 ``/api/workbench/employee-publish`` 发布。
    """
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
    from modstore_server.csv_tabular_runtime import is_csv_full_read, is_csv_generate
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.excel_tabular_runtime import is_excel_full_read, is_excel_generate
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate
    from modstore_server.txt_extract_runtime import is_txt_full_read, is_txt_generate
    from modstore_server.word_extract_runtime import is_word_full_extract
    from modstore_server.word_generate_runtime import is_word_generate

    rb = extract_routing_brief({"brief": brief}, fallback=brief)
    if is_csv_full_read(rb) or is_csv_generate(rb):
        return {
            "ok": False,
            "error": "CSV 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_excel_full_read(rb) or is_excel_generate(rb):
        return {
            "ok": False,
            "error": "Excel 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_txt_full_read(rb) or is_txt_generate(rb):
        return {
            "ok": False,
            "error": "TXT 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_pdf_full_read(rb) or is_pdf_generate(rb):
        return {
            "ok": False,
            "error": "PDF 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_full_extract(rb):
        return {
            "ok": False,
            "error": "Word 全量提取必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_generate(rb):
        return {
            "ok": False,
            "error": "Word 生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return {"ok": False, "error": "该供应商未配置可用 API Key（平台或 BYOK）"}
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT_EMPLOYEE},
        {"role": "user", "content": brief},
    ]
    result = await _facade().chat_dispatch(
        prov, api_key=api_key, base_url=base, model=mdl, messages=msgs, max_tokens=6000
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    (manifest, perr) = _facade().parse_employee_pack_llm_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出"}
    from modstore_server.employee_ai_scaffold import _is_template_brief, _validate_skill_quality

    _v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    _cognition = _v2.get("cognition") if isinstance(_v2.get("cognition"), dict) else {}
    _skills = _cognition.get("skills") if isinstance(_cognition.get("skills"), list) else []
    _emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    _label = str(_emp.get("label") or manifest.get("name") or "").strip()
    _desc = str(manifest.get("description") or "").strip()
    _poor_briefs = sum(
        (
            1
            for sk in _skills
            if isinstance(sk, dict) and _is_template_brief(str(sk.get("brief") or ""))
        )
    )
    if _poor_briefs > 0 and len(_skills) > 0:
        _retry_prompt = f"""上一次生成的员工技能描述质量不足，包含模板化套话。请重新为以下技能生成具体的、有业务语义的 brief 描述。\n每个 brief 必须说明：该技能做什么、处理什么输入、输出什么结果。不要使用'围绕...执行...相关任务'这种套话。\n只输出 JSON 数组，不要 markdown 围栏：\n[{{"name":"技能id","brief":"具体描述"}}]\n\n技能列表：{_facade().json.dumps([{'name': sk.get('name'), 'brief': sk.get('brief')} for sk in _skills if isinstance(sk, dict)], ensure_ascii=False)}\n员工名称：{_label}\n员工描述：{_desc}"""
        try:
            _retry_result = await _facade().chat_dispatch(
                prov,
                api_key=api_key,
                base_url=base,
                model=mdl,
                messages=[{"role": "user", "content": _retry_prompt}],
                max_tokens=2000,
            )
            if _retry_result.get("ok"):
                import re as _re

                _retry_raw = _re.sub(
                    "^```(?:json)?\\s*",
                    "",
                    (_retry_result.get("content") or "").strip(),
                    flags=_re.I,
                )
                _retry_raw = _re.sub("\\s*```\\s*$", "", _retry_raw).strip()
                _retry_skills = _facade().json.loads(_retry_raw)
                if isinstance(_retry_skills, list):
                    _name_to_brief = {}
                    for rsk in _retry_skills:
                        if isinstance(rsk, dict):
                            _rn = str(rsk.get("name") or "").strip()
                            _rb = str(rsk.get("brief") or "").strip()
                            if _rn and _rb and (not _is_template_brief(_rb)):
                                _name_to_brief[_rn] = _rb
                    for sk in _skills:
                        if isinstance(sk, dict):
                            _sn = str(sk.get("name") or "").strip()
                            if _sn in _name_to_brief:
                                sk["brief"] = _name_to_brief[_sn]
                    _cognition["skills"] = _validate_skill_quality(
                        _skills, label=_label, description=_desc
                    )
                    _v2["cognition"] = _cognition
                    manifest["employee_config_v2"] = _v2
        except Exception:
            _cognition["skills"] = _validate_skill_quality(_skills, label=_label, description=_desc)
            _v2["cognition"] = _cognition
            manifest["employee_config_v2"] = _v2
    pid = str(manifest.get("id") or "").strip()
    lib = _facade().modstore_library_path()
    if (lib / pid).is_dir() and (not replace):
        return {"ok": False, "error": f"包 {pid} 已存在，请传 replace=true 覆盖"}
    raw_zip = _facade().build_employee_pack_zip(pid, manifest)
    with _facade().tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, lib, replace=replace)
    except (ValueError, FileExistsError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)
    _facade().add_user_mod(user.id, dest.name)
    saved_package: _facade().Dict[str, _facade().Any] = {}
    if publish_to_catalog:
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            pkg_tmp_path = _facade().Path(tmp.name)
        try:
            from modstore_server.catalog_store import append_package
            from modstore_server.models import CatalogItem

            rec = {
                "id": pid,
                "name": str(manifest.get("name") or pid),
                "version": str(manifest.get("version") or "1.0.0"),
                "description": str(manifest.get("description") or ""),
                "artifact": "employee_pack",
                "industry": str(manifest.get("industry") or "通用"),
                "release_channel": "stable",
                "commerce": {"mode": "free", "price": 0},
                "license": {"type": "personal", "verify_url": None},
            }
            saved_package = append_package(rec, pkg_tmp_path)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if not row:
                row = CatalogItem(pkg_id=pid, author_id=user.id)
                db.add(row)
            row.version = saved_package.get("version") or rec["version"]
            row.name = saved_package.get("name") or rec["name"]
            row.description = saved_package.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved_package.get("industry") or rec["industry"]
            row.stored_filename = saved_package.get("stored_filename") or ""
            row.sha256 = saved_package.get("sha256") or ""
            db.commit()
        finally:
            pkg_tmp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "package": saved_package,
        "published": bool(publish_to_catalog and saved_package),
    }
