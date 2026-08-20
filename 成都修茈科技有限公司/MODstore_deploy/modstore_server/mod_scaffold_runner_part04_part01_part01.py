# mypy: disable-error-code="attr-defined, dict-item, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
        gen: _facade().Dict[str, _facade().Any] = {
            "ok": True,
            "parsed": manifest_override,
        }
    else:
        gen = await _facade().generate_mod_suite_blueprint_async(
            db,
            user,
            brief=brief,
            suggested_id=suggested_id,
            provider=provider,
            model=model,
        )
    if not gen.get("ok"):
        return gen
    imported = _facade().import_mod_suite_repository(
        db,
        user,
        parsed=gen["parsed"],
        replace=replace,
        generate_frontend=generate_frontend,
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
    api_summary = {
        "nodes": wf.get("api_nodes") or [],
        "warnings": wf.get("api_warnings") or [],
    }
    employee_readiness = _facade().analyze_mod_employee_readiness(db, user, dest)
    pack_registration: _facade().Dict[str, _facade().Any] = {
        "registered": [],
        "errors": [],
    }
    if employees:
        try:
            pack_registration = await _facade().register_mod_employee_packs_async(
                db,
                user,
                mod_dir=dest,
                workflow_results=workflow_results,
                industry=str(manifest.get("industry") or "通用"),
            )
        except RECOVERABLE_ERRORS:
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
            data, err = _read_manifest(dest)
            if not err and data:
                manifest = data
        except RECOVERABLE_ERRORS:
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
    data, err = (None, None)
    try:
        from modman.manifest_util import read_manifest

        data, err = read_manifest(dest)
    except RECOVERABLE_ERRORS:
        data, err = (None, None)
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
    except RECOVERABLE_ERRORS as exc:
        return {"enabled": False, "reason": f"vibe coder 构造失败: {exc}"}
    try:
        idx = coder.index_project(refresh=True)
    except RECOVERABLE_ERRORS as exc:
        return {"enabled": True, "ok": False, "reason": f"index_project 失败: {exc}"}
    summary: _facade().Dict[str, _facade().Any] = {"enabled": True, "ok": True}
    try:
        if hasattr(idx, "summary") and callable(idx.summary):
            summary["summary"] = idx.summary()
        else:
            summary["summary"] = {
                "files": getattr(idx, "files_count", None) or len(getattr(idx, "files", []) or [])
            }
    except RECOVERABLE_ERRORS as exc:
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
        except RECOVERABLE_ERRORS:
            pass
    eskill_specs: list[dict] = []
    try:
        from modstore_server.employee_skill_register import (
            register_employee_pack_as_eskills,
        )

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
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS:
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
            {
                "eskill_id": s["eskill_id"],
                "name": s["name"],
                "vibe_skill_id": s["vibe_skill_id"],
            }
            for s in eskill_specs
        ],
    }
    try:
        from modstore_server.employee_pack_workflow_bundle import (
            embed_workflow_bundles_in_manifest,
        )

        embed_workflow_bundles_in_manifest(db, raw)
    except RECOVERABLE_ERRORS as _bundle_exc:
        _facade().logger.warning(
            "attach_nl_workflow: embed bundles failed wf_id=%d: %s", wf.id, _bundle_exc
        )
    mf.write_text(_facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from modstore_server.employee_asset_pipeline import (
            reconcile_employee_pack_manifest,
        )

        reconcile_employee_pack_manifest(pack_dir, brief=(brief or "").strip())
    except RECOVERABLE_ERRORS as _rec_exc:
        _facade().logger.warning("attach_nl_workflow: manifest reconcile failed: %s", _rec_exc)
    return {
        "ok": True,
        "automation_complete": True,
        "workflow_id": wf.id,
        "nl": nl,
        "eskill_count": len(eskill_specs),
    }
