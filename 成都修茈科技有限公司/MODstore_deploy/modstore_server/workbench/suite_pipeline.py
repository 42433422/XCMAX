"""Suite pipeline for workbench delivery."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, cast

from sqlalchemy.orm import Session

from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem
from modstore_server.models import CatalogItem, Workflow, WorkflowEdge, WorkflowNode
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")
_MAX_EMPLOYEES_FOR_LLM = 10


def _safe_fallback_employee_source() -> str:
    """Return the repository-owned generic fallback source for compatibility."""
    return _fallback_employee_template_path().read_text(encoding="utf-8")


def _fallback_employee_template_path() -> Path:
    return Path(__file__).with_name("_generic_fallback_employee.py")


def _copy_fallback_employee_source(destination: Path) -> None:
    """Copy a fixed, private-data-free source asset into the generated MOD."""
    shutil.copyfile(_fallback_employee_template_path(), destination)


@dataclass(frozen=True)
class SuitePorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    readiness: Callable[..., dict[str, Any]]
    create_workflows: Callable[..., Awaitable[dict[str, Any]]]
    generate_employees: Callable[..., Awaitable[dict[str, Any]]]
    blueprint: Callable[..., Awaitable[dict[str, Any]]]
    import_repository: Callable[..., dict[str, Any]]
    compile_warnings: Callable[..., list[str]]
    patch_employee_nodes: Callable[..., Any]
    register_employees: Callable[..., Awaitable[dict[str, Any]]]
    scaffold: Callable[..., Awaitable[dict[str, Any]]]
    mod_sandbox: Callable[..., dict[str, Any]]
    workflow_sandboxes: Callable[..., dict[str, Any]]
    write_blueprint: Callable[..., Any]
    write_industry: Callable[..., Any]
    write_ui: Callable[..., Any]


def _cleanup_mod_pipeline_resources(db: Session, resources: List[Dict[str, Any]]) -> None:
    """做 Mod 全流程失败时尽量撤销已创建目录与数据库记录（尽力而为）。"""
    import shutil

    for res in reversed(resources):
        try:
            if res["type"] == "mod_dir":
                p = Path(res["path"])
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
            elif res["type"] == "workflow_ids":
                for wid in res.get("ids") or []:
                    try:
                        wid_int = int(wid)
                    except (TypeError, ValueError):
                        continue
                    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wid_int).delete(
                        synchronize_session=False
                    )
                    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wid_int).delete(
                        synchronize_session=False
                    )
                    wf = db.query(Workflow).filter(Workflow.id == wid_int).first()
                    if wf:
                        db.delete(wf)
                db.commit()
            elif res["type"] == "catalog_by_pkg":
                pkg_id = str(res.get("pkg_id") or "").strip()
                if pkg_id:
                    db.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).delete(
                        synchronize_session=False
                    )
                    db.commit()
        except RECOVERABLE_ERRORS:
            _LOG.exception("cleanup pipeline resource failed res=%s", res)


async def _run_workbench_mod_pipeline(
    sid,
    payload,
    intent,
    brief,
    prov,
    mdl,
    replace,
    generate_frontend,
    db,
    user,
    *,
    ports: SuitePorts,
):
    if not bool(payload.get("generate_full_suite", True)):
        await ports.progress.set_step(sid, "manifest", "running", "正在生成最小 manifest")
        res = await ports.scaffold(
            db,
            user,
            brief=brief,
            suggested_id=payload.get("suggested_mod_id"),
            replace=replace,
            provider=prov,
            model=mdl,
        )
        if not res.get("ok"):
            await ports.progress.fail(sid, "manifest", res.get("error") or "生成失败")
            return
        await ports.progress.set_step(sid, "manifest", "done", "manifest 已生成")
        await ports.progress.set_step(sid, "repo", "done", f"Mod 仓库：{res.get('id')}")
        for skipped in (
            "industry",
            "employees",
            "workflows",
            "api",
            "workflow_sandbox",
        ):
            await ports.progress.set_step(sid, skipped, "skipped", "最小 Mod 模式跳过")
        await ports.progress.set_step(sid, "mod_sandbox", "running", "正在做轻量 Mod 校验")
        mod_dir = Path(res["path"])
        warns = ports.compile_warnings(mod_dir)
        await ports.progress.set_step(
            sid, "mod_sandbox", "done", "；".join(warns) if warns else "轻量校验通过"
        )
        await ports.progress.set_step(sid, "complete", "done")
        async with ports.sessions.lock:
            sess = ports.sessions.data.get(sid)
            if sess:
                sess["validate_warnings"] = warns
                ports.sessions.persist(sid)
        await ports.progress.finish(
            sid,
            {
                "mod_id": res["id"],
                "workflow_results": [],
                "blueprint": None,
                "validation_summary": {"ok": not warns, "python_warnings": warns},
            },
        )
        return
    await ports.progress.set_step(sid, "manifest", "running", "正在生成结构化 Mod 蓝图 JSON")
    gen = await ports.blueprint(
        db,
        user,
        brief=brief,
        suggested_id=payload.get("suggested_mod_id"),
        provider=prov,
        model=mdl,
    )
    if not gen.get("ok"):
        await ports.progress.fail(sid, "manifest", gen.get("error") or "蓝图生成失败")
        return
    parsed = gen["parsed"]
    manifest = parsed["manifest"]
    employees = parsed.get("employees") or []
    blueprint = parsed.get("blueprint") or {}
    repair_note = "；已自动修复 JSON" if gen.get("repair_used") else ""
    await ports.progress.set_step(
        sid,
        "manifest",
        "done",
        f"manifest.id={manifest.get('id')}，员工 {len(employees)} 名{repair_note}",
    )
    _pipeline_resources: List[Dict[str, Any]] = []

    async def _abort_mod_pipeline(step_id: str, err: str) -> None:
        _cleanup_mod_pipeline_resources(db, _pipeline_resources)
        await ports.progress.fail(sid, step_id, err)

    try:
        await ports.progress.set_step(sid, "repo", "running", "正在新建或覆盖 Mod 仓库")
        imported = ports.import_repository(
            db,
            user,
            parsed=parsed,
            replace=replace,
            generate_frontend=generate_frontend,
        )
        if not imported.get("ok"):
            await ports.progress.fail(sid, "repo", imported.get("error") or "Mod 仓库创建失败")
            return
        blueprint = parsed.get("blueprint") or blueprint
        mod_dir = Path(imported["path"])
        _pipeline_resources.append({"type": "mod_dir", "path": str(mod_dir)})
        repo_done = f"已写入 {imported.get('id')}"
        if generate_frontend:
            repo_done += "；含 Vue 定制页（frontend/routes.js、frontend/views/HomeView.vue）" + (
                "，frontend_app 由模型省略已自动补齐"
                if imported.get("had_frontend_fallback")
                else ""
            )
        await ports.progress.set_step(sid, "repo", "done", repo_done)
        await ports.progress.set_step(sid, "industry", "running", "正在写入行业卡片")
        try:
            industry_card = ports.write_industry(mod_dir, blueprint)
            ui_shell = ports.write_ui(mod_dir, blueprint)
        except RECOVERABLE_ERRORS as e:
            await _abort_mod_pipeline("industry", f"行业/UI 配置生成失败: {e}")
            return
        await ports.progress.set_step(
            sid,
            "industry",
            "done",
            f"{industry_card.get('name') or '通用'}；侧栏 {len(ui_shell.get('sidebar_menu') or [])} 项",
        )
        await ports.progress.set_step(
            sid, "employees", "running", f"正在创建 {len(employees)} 名员工骨架"
        )
        await ports.progress.set_step(
            sid, "employees", "done", f"已写入 workflow_employees：{len(employees)} 名"
        )
        employees_for_llm = employees[:_MAX_EMPLOYEES_FOR_LLM]
        if len(employees) > _MAX_EMPLOYEES_FOR_LLM:
            await ports.progress.set_step(
                sid,
                "employee_impls",
                "running",
                f"员工数 {len(employees)} 超过 LLM 上限 {_MAX_EMPLOYEES_FOR_LLM}，仅前 {_MAX_EMPLOYEES_FOR_LLM} 名请求模型；其余写入兜底实现…",
            )
            emp_dir = mod_dir / "backend" / "employees"
            emp_dir.mkdir(parents=True, exist_ok=True)
            for emp in employees[_MAX_EMPLOYEES_FOR_LLM:]:
                if not isinstance(emp, dict):
                    continue
                eid = str(emp.get("id") or "").strip()
                if not eid:
                    continue
                stem = sanitize_employee_stem(eid)
                # The fallback implementation is a static, repository-owned asset.
                # Profile/request data remains in the existing manifest only.
                _copy_fallback_employee_source(emp_dir / f"{stem}.py")
        await ports.progress.set_step(
            sid, "employee_impls", "running", "开始为每员工生成可执行脚本…"
        )

        async def _emp_impl_step_msg(text: str) -> None:
            await ports.progress.set_step(sid, "employee_impls", "running", text)

        try:
            impl_result = await ports.generate_employees(
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
            _LOG.exception("workbench mod employee_impls failed session=%s", sid)
            await _abort_mod_pipeline(
                "employee_impls",
                f"生成员工脚本异常（可查看服务端日志）: {exc!s}"[:1000],
            )
            return
        impl_errs = impl_result.get("errors") or []
        impl_done_msg = f"已生成 {len(impl_result.get('generated') or [])} 份员工脚本" + (
            f"，{len(impl_errs)} 份走兜底实现" if impl_errs else ""
        )
        await ports.progress.set_step(sid, "employee_impls", "done", impl_done_msg)
        await ports.progress.set_step(
            sid,
            "workflows",
            "running",
            "开始生成员工 Skill 组（画布节点与连线；ESkill 口径下单节点即 Skill）…",
        )

        async def _workflows_step_msg(text: str) -> None:
            await ports.progress.set_step(sid, "workflows", "running", text)

        wf = await ports.create_workflows(
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
        await ports.progress.set_step(
            sid,
            "workflows",
            "done",
            f"已生成 {len(workflow_results)} 条工作流，失败 {len(failed_workflows)} 条",
        )
        if failed_workflows:
            _fw_msg = f"工作流自动化未完成 {len(failed_workflows)} 条，已跳过登记员工包（须 workflow-automator 修复后再 register_packs）"
            await ports.progress.set_step(sid, "register_packs", "error", _fw_msg[:480])
            await ports.progress.fail(sid, "register_packs", _fw_msg[:1000])
            return
        await ports.progress.set_step(sid, "register_packs", "running", "修复画布员工节点对齐…")
        graph_patch_result = ports.patch_employee_nodes(
            db, user, mod_dir=mod_dir, workflow_results=workflow_results
        )

        async def _register_step_msg(text: str) -> None:
            await ports.progress.set_step(sid, "register_packs", "running", text)

        register_result = await ports.register_employees(
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
        await ports.progress.set_step(sid, "register_packs", "done", reg_done_msg)
        await ports.progress.set_step(sid, "api", "running", "正在汇总 OpenAPI 节点")
        api_summary: dict[str, Any] = {
            "nodes": wf.get("api_nodes") or [],
            "warnings": wf.get("api_warnings") or [],
        }
        api_msg = f"发现 {len(api_summary['nodes'])} 个 API 节点" + (
            f"，{len(api_summary['warnings'])} 个待配置" if api_summary["warnings"] else ""
        )
        await ports.progress.set_step(sid, "api", "done", api_msg)
        await ports.progress.set_step(
            sid, "workflow_sandbox", "running", "正在 mock 执行员工工作流"
        )
        workflow_sandbox = ports.workflow_sandboxes(db, user, workflow_results)
        await ports.progress.set_step(
            sid,
            "workflow_sandbox",
            "done",
            (
                "结构沙盒（Mock 员工）通过"
                if workflow_sandbox.get("ok")
                else "结构沙盒存在警告，请进入画布检查"
            ),
        )
        employee_readiness = ports.readiness(db, user, mod_dir)
        blueprint["employee_impl_result"] = impl_result
        blueprint["graph_patch_result"] = graph_patch_result
        blueprint["pack_register_result"] = register_result
        vibe_heal_report = impl_result.get("vibe_heal") if isinstance(impl_result, dict) else None
        ports.write_blueprint(
            mod_dir,
            blueprint,
            workflow_results,
            industry_card=industry_card,
            ui_shell=ui_shell,
            api_summary=api_summary,
            workflow_sandbox=workflow_sandbox,
            employee_readiness=employee_readiness,
            vibe_heal=(
                cast(dict[str, Any], vibe_heal_report)
                if isinstance(vibe_heal_report, dict)
                else None
            ),
        )
        await ports.progress.set_step(
            sid, "mod_sandbox", "running", "正在校验 Mod manifest、蓝图与路由骨架"
        )
        mod_sandbox = ports.mod_sandbox(mod_dir, workflow_results)
        validation_summary: dict[str, Any] = {
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
        await ports.progress.set_step(
            sid,
            "mod_sandbox",
            "done",
            (
                "Mod 沙箱通过；员工真实执行仍需登记与非 Mock 验证"
                if mod_sandbox.get("ok") and employee_readiness.get("ok")
                else "Mod 沙箱或员工可用性存在缺口，已写入报告"
            ),
        )
        await ports.progress.set_step(sid, "complete", "done")
        async with ports.sessions.lock:
            sess = ports.sessions.data.get(sid)
            if sess:
                sess["validate_warnings"] = (
                    api_summary["warnings"] + validation_summary["workflow_warnings"]
                )
                sess["sandbox_report"] = {
                    "workflow": workflow_sandbox,
                    "mod": mod_sandbox,
                }
                ports.sessions.persist(sid)
        await ports.progress.finish(
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
        _LOG.exception("workbench mod full suite failed session=%s", sid)
        await _abort_mod_pipeline("complete", str(e)[:2000])
        return
    return
