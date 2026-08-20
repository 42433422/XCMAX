"""Workbench mod pipeline branch."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_workbench_mod_pipeline(
    sid, payload, intent, brief, prov, mdl, replace, generate_frontend, db, user
):
    if not bool(payload.get("generate_full_suite", True)):
        await _facade()._set_step(sid, "manifest", "running", "正在生成最小 manifest")
        res = await _facade().run_mod_ai_scaffold_async(
            db,
            user,
            brief=brief,
            suggested_id=payload.get("suggested_mod_id"),
            replace=replace,
            provider=prov,
            model=mdl,
        )
        if not res.get("ok"):
            await _facade()._fail_session(sid, "manifest", res.get("error") or "生成失败")
            return
        await _facade()._set_step(sid, "manifest", "done", "manifest 已生成")
        await _facade()._set_step(sid, "repo", "done", f"Mod 仓库：{res.get('id')}")
        for skipped in (
            "industry",
            "employees",
            "workflows",
            "api",
            "workflow_sandbox",
        ):
            await _facade()._set_step(sid, skipped, "skipped", "最小 Mod 模式跳过")
        await _facade()._set_step(sid, "mod_sandbox", "running", "正在做轻量 Mod 校验")
        mod_dir = _facade().Path(res["path"])
        warns = _facade().mod_compileall_warnings(mod_dir)
        await _facade()._set_step(
            sid, "mod_sandbox", "done", "；".join(warns) if warns else "轻量校验通过"
        )
        await _facade()._set_step(sid, "complete", "done")
        async with _facade()._SESSION_LOCK:
            sess = _facade().WORKBENCH_SESSIONS.get(sid)
            if sess:
                sess["validate_warnings"] = warns
                _facade()._persist_workbench_session_unlocked(sid)
        await _facade()._finalize_session_done(
            sid,
            {
                "mod_id": res["id"],
                "workflow_results": [],
                "blueprint": None,
                "validation_summary": {"ok": not warns, "python_warnings": warns},
            },
        )
        return
    await _facade()._set_step(sid, "manifest", "running", "正在生成结构化 Mod 蓝图 JSON")
    gen = await _facade().generate_mod_suite_blueprint_async(
        db,
        user,
        brief=brief,
        suggested_id=payload.get("suggested_mod_id"),
        provider=prov,
        model=mdl,
    )
    if not gen.get("ok"):
        await _facade()._fail_session(sid, "manifest", gen.get("error") or "蓝图生成失败")
        return
    parsed = gen["parsed"]
    manifest = parsed["manifest"]
    employees = parsed.get("employees") or []
    blueprint = parsed.get("blueprint") or {}
    repair_note = "；已自动修复 JSON" if gen.get("repair_used") else ""
    await _facade()._set_step(
        sid,
        "manifest",
        "done",
        f"manifest.id={manifest.get('id')}，员工 {len(employees)} 名{repair_note}",
    )
    _pipeline_resources: _facade().List[_facade().Dict[str, _facade().Any]] = []

    async def _abort_mod_pipeline(step_id: str, err: str) -> None:
        _facade()._cleanup_mod_pipeline_resources(db, _pipeline_resources)
        await _facade()._fail_session(sid, step_id, err)

    try:
        await _facade()._set_step(sid, "repo", "running", "正在新建或覆盖 Mod 仓库")
        imported = _facade().import_mod_suite_repository(
            db,
            user,
            parsed=parsed,
            replace=replace,
            generate_frontend=generate_frontend,
        )
        if not imported.get("ok"):
            await _facade()._fail_session(sid, "repo", imported.get("error") or "Mod 仓库创建失败")
            return
        blueprint = parsed.get("blueprint") or blueprint
        mod_dir = _facade().Path(imported["path"])
        _pipeline_resources.append({"type": "mod_dir", "path": str(mod_dir)})
        repo_done = f"已写入 {imported.get('id')}"
        if generate_frontend:
            repo_done += "；含 Vue 定制页（frontend/routes.js、frontend/views/HomeView.vue）" + (
                "，frontend_app 由模型省略已自动补齐"
                if imported.get("had_frontend_fallback")
                else ""
            )
        await _facade()._set_step(sid, "repo", "done", repo_done)
        await _facade()._set_step(sid, "industry", "running", "正在写入行业卡片")
        try:
            industry_card = _facade().write_mod_suite_industry_card(mod_dir, blueprint)
            ui_shell = _facade().write_mod_suite_ui_shell(mod_dir, blueprint)
        except RECOVERABLE_ERRORS as e:
            await _abort_mod_pipeline("industry", f"行业/UI 配置生成失败: {e}")
            return
        await _facade()._set_step(
            sid,
            "industry",
            "done",
            f"{industry_card.get('name') or '通用'}；侧栏 {len(ui_shell.get('sidebar_menu') or [])} 项",
        )
        await _facade()._set_step(
            sid, "employees", "running", f"正在创建 {len(employees)} 名员工骨架"
        )
        await _facade()._set_step(
            sid, "employees", "done", f"已写入 workflow_employees：{len(employees)} 名"
        )
        employees_for_llm = employees[: _facade()._MAX_EMPLOYEES_FOR_LLM]
        if len(employees) > _facade()._MAX_EMPLOYEES_FOR_LLM:
            await _facade()._set_step(
                sid,
                "employee_impls",
                "running",
                f"员工数 {len(employees)} 超过 LLM 上限 {_facade()._MAX_EMPLOYEES_FOR_LLM}，仅前 {_facade()._MAX_EMPLOYEES_FOR_LLM} 名请求模型；其余写入兜底实现…",
            )
            emp_dir = mod_dir / "backend" / "employees"
            emp_dir.mkdir(parents=True, exist_ok=True)
            for emp in employees[_facade()._MAX_EMPLOYEES_FOR_LLM :]:
                if not isinstance(emp, dict):
                    continue
                eid = str(emp.get("id") or "").strip()
                if not eid:
                    continue
                stem = _facade().sanitize_employee_stem(eid)
                label = str(emp.get("label") or emp.get("panel_title") or eid).strip()
                panel_summary = str(emp.get("panel_summary") or "").strip()
                fb = _facade()._fallback_employee_py(eid, label, panel_summary)
                (emp_dir / f"{stem}.py").write_text(fb, encoding="utf-8")
        await _facade()._set_step(sid, "employee_impls", "running", "开始为每员工生成可执行脚本…")

        async def _emp_impl_step_msg(text: str) -> None:
            await _facade()._set_step(sid, "employee_impls", "running", text)

        try:
            impl_result = await _facade().generate_mod_employee_impls_async(
                db,
                user,
                mod_dir=mod_dir,
                employees=employees_for_llm,
                mod_id=str(manifest.get("id") or mod_dir.name),
                mod_name=str(manifest.get("name") or manifest.get("id") or mod_dir.name),
                mod_brief=brief,
                industry_card=industry_card,
                provider=gen.get("provider"),
                model=gen.get("model"),
                status_hook=_emp_impl_step_msg,
            )
        except RECOVERABLE_ERRORS as exc:
            _facade()._LOG.exception("workbench mod employee_impls failed session=%s", sid)
            await _abort_mod_pipeline(
                "employee_impls",
                f"生成员工脚本异常（可查看服务端日志）: {exc!s}"[:1000],
            )
            return
        impl_errs = impl_result.get("errors") or []
        impl_done_msg = f"已生成 {len(impl_result.get('generated') or [])} 份员工脚本" + (
            f"，{len(impl_errs)} 份走兜底实现" if impl_errs else ""
        )
        await _facade()._set_step(sid, "employee_impls", "done", impl_done_msg)
        await _facade()._set_step(
            sid,
            "workflows",
            "running",
            "开始生成员工 Skill 组（画布节点与连线；ESkill 口径下单节点即 Skill）…",
        )

        async def _workflows_step_msg(text: str) -> None:
            await _facade()._set_step(sid, "workflows", "running", text)

        wf = await _facade().create_mod_suite_workflows_async(
            db,
            user,
            mod_dir=mod_dir,
            employees=employees,
            brief=brief,
            provider=gen.get("provider"),
            model=gen.get("model"),
            step_message_hook=_workflows_step_msg,
        )
        workflow_results = wf.get("workflow_results") or []
        wf_ids = [
            x.get("workflow_id")
            for x in workflow_results
            if isinstance(x, dict) and x.get("workflow_id") is not None
        ]
        _pipeline_resources.append({"type": "workflow_ids", "ids": wf_ids})
        failed_workflows = [
            x for x in workflow_results if isinstance(x, dict) and (not x.get("ok", True))
        ]
        await _facade()._set_step(
            sid,
            "workflows",
            "done",
            f"已生成 {len(workflow_results)} 条工作流，失败 {len(failed_workflows)} 条",
        )
        if failed_workflows:
            _fw_msg = f"工作流自动化未完成 {len(failed_workflows)} 条，已跳过登记员工包（须 workflow-automator 修复后再 register_packs）"
            await _facade()._set_step(sid, "register_packs", "error", _fw_msg[:480])
            await _facade()._fail_session(sid, "register_packs", _fw_msg[:1000])
            return
        await _facade()._set_step(sid, "register_packs", "running", "修复画布员工节点对齐…")
        graph_patch_result = _facade().patch_workflow_graph_employee_nodes(
            db, user, mod_dir=mod_dir, workflow_results=workflow_results
        )

        async def _register_step_msg(text: str) -> None:
            await _facade()._set_step(sid, "register_packs", "running", text)

        register_result = await _facade().register_mod_employee_packs_async(
            db,
            user,
            mod_dir=mod_dir,
            workflow_results=workflow_results,
            status_hook=_register_step_msg,
            industry=str((industry_card or {}).get("name") or "通用"),
        )
        _pipeline_resources.append(
            {
                "type": "catalog_by_pkg",
                "pkg_id": str(imported.get("id") or manifest.get("id") or mod_dir.name),
            }
        )
        reg_errs = register_result.get("errors") or []
        patches = graph_patch_result.get("patches") or []
        patch_updates = sum((1 for p in patches if p.get("action") in ("update", "insert")))
        reg_done_msg = f"画布修复 {patch_updates} 处；已登记 {len(register_result.get('registered') or [])} 个员工包" + (
            f"，{len(reg_errs)} 个失败" if reg_errs else ""
        )
        await _facade()._set_step(sid, "register_packs", "done", reg_done_msg)
        await _facade()._set_step(sid, "api", "running", "正在汇总 OpenAPI 节点")
        api_summary = {
            "nodes": wf.get("api_nodes") or [],
            "warnings": wf.get("api_warnings") or [],
        }
        api_msg = f"发现 {len(api_summary['nodes'])} 个 API 节点" + (
            f"，{len(api_summary['warnings'])} 个待配置" if api_summary["warnings"] else ""
        )
        await _facade()._set_step(sid, "api", "done", api_msg)
        await _facade()._set_step(sid, "workflow_sandbox", "running", "正在 mock 执行员工工作流")
        workflow_sandbox = _facade().run_mod_suite_workflow_sandboxes(db, user, workflow_results)
        await _facade()._set_step(
            sid,
            "workflow_sandbox",
            "done",
            (
                "结构沙盒（Mock 员工）通过"
                if workflow_sandbox.get("ok")
                else "结构沙盒存在警告，请进入画布检查"
            ),
        )
        employee_readiness = _facade().analyze_mod_employee_readiness(db, user, mod_dir)
        blueprint["employee_impl_result"] = impl_result
        blueprint["graph_patch_result"] = graph_patch_result
        blueprint["pack_register_result"] = register_result
        vibe_heal_report = impl_result.get("vibe_heal") if isinstance(impl_result, dict) else None
        _facade().write_mod_suite_blueprint(
            mod_dir,
            blueprint,
            workflow_results,
            industry_card=industry_card,
            ui_shell=ui_shell,
            api_summary=api_summary,
            workflow_sandbox=workflow_sandbox,
            employee_readiness=employee_readiness,
            vibe_heal=vibe_heal_report if isinstance(vibe_heal_report, dict) else None,
        )
        await _facade()._set_step(
            sid, "mod_sandbox", "running", "正在校验 Mod manifest、蓝图与路由骨架"
        )
        mod_sandbox = _facade().run_mod_suite_mod_sandbox(mod_dir, workflow_results)
        validation_summary = {
            "mod_sandbox": mod_sandbox,
            "api_warnings": api_summary["warnings"],
            "workflow_warnings": [
                str(item.get("error") or item.get("graph", {}).get("error") or "")
                for item in workflow_results
                if isinstance(item, dict) and (not item.get("ok", True))
            ],
            "repair_suggestions": [],
            "employee_readiness": employee_readiness,
            "ok": bool(mod_sandbox.get("ok"))
            and (not failed_workflows)
            and bool(employee_readiness.get("ok")),
        }
        await _facade()._set_step(
            sid,
            "mod_sandbox",
            "done",
            (
                "Mod 沙箱通过；员工真实执行仍需登记与非 Mock 验证"
                if mod_sandbox.get("ok") and employee_readiness.get("ok")
                else "Mod 沙箱或员工可用性存在缺口，已写入报告"
            ),
        )
        await _facade()._set_step(sid, "complete", "done")
        async with _facade()._SESSION_LOCK:
            sess = _facade().WORKBENCH_SESSIONS.get(sid)
            if sess:
                sess["validate_warnings"] = (
                    api_summary["warnings"] + validation_summary["workflow_warnings"]
                )
                sess["sandbox_report"] = {
                    "workflow": workflow_sandbox,
                    "mod": mod_sandbox,
                }
                _facade()._persist_workbench_session_unlocked(sid)
        await _facade()._finalize_session_done(
            sid,
            {
                "mod_id": imported["id"],
                "workflow_results": workflow_results,
                "blueprint": blueprint,
                "industry_card": industry_card,
                "ui_shell": ui_shell,
                "api_summary": api_summary,
                "workflow_sandbox": workflow_sandbox,
                "employee_readiness": employee_readiness,
                "mod_sandbox": mod_sandbox,
                "validation_summary": validation_summary,
                "employee_impls": impl_result,
                "graph_patch": graph_patch_result,
                "pack_register": register_result,
            },
        )
    except RECOVERABLE_ERRORS as e:
        _facade()._LOG.exception("workbench mod full suite failed session=%s", sid)
        await _abort_mod_pipeline("complete", str(e)[:2000])
        return
    return
