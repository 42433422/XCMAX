# mypy: disable-error-code="arg-type, attr-defined, call-arg, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def import_mod_suite_repository(
    db: _facade().Session,
    user: _facade().User,
    *,
    parsed: _facade().Dict[str, _facade().Any],
    replace: bool = True,
    generate_frontend: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    manifest = parsed["manifest"]
    employees = parsed.get("employees") or []
    blueprint = parsed.get("blueprint") or {}
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    lib = _facade().modstore_library_path()
    dest_path = lib / mid
    if dest_path.is_dir() and (not replace):
        return {
            "ok": False,
            "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述",
        }
    employees_for_routes = _facade().merge_employees_for_blueprint_routes(manifest, employees)
    extra_files = {
        "backend/blueprints.py": _facade().render_suite_blueprints_py(
            mid, mname, employees_for_routes
        ),
        "config/ai_blueprint.json": _facade()._suite_blueprint_file(blueprint, []),
        "config/industry_card.json": _facade().json.dumps(
            _facade()._mod_suite_industry_card_payload(blueprint),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "config/ui_shell.json": _facade().json.dumps(
            _facade()._mod_suite_ui_shell_payload(blueprint),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    }
    frontend_app = (
        blueprint.get("frontend_app") if isinstance(blueprint.get("frontend_app"), dict) else {}
    )
    had_frontend_fallback = False
    if generate_frontend and (not frontend_app):
        desc = str(manifest.get("description") or "").strip()
        industry_payload = _facade()._sanitize_industry(
            blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {},
            mod_name=mname,
            description=desc,
        )
        fe = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
        menu_raw = fe.get("menu") if isinstance(fe.get("menu"), list) else None
        fm = _facade()._normalize_frontend_menu(menu_raw, mod_id=mid, mod_name=mname)
        bp_emp = blueprint.get("employees") if isinstance(blueprint.get("employees"), list) else []
        emp_for_fe = employees if employees else bp_emp
        if not isinstance(emp_for_fe, list):
            emp_for_fe = []
        frontend_app = _facade()._normalize_frontend_app(
            {},
            mod_id=mid,
            mod_name=mname,
            description=desc,
            industry=industry_payload,
            employees=emp_for_fe,
            frontend_menu=fm,
        )
        had_frontend_fallback = True
        if isinstance(blueprint, dict):
            blueprint["frontend_app"] = frontend_app
        if isinstance(parsed, dict):
            bp_store = parsed.get("blueprint")
            if not isinstance(bp_store, dict):
                parsed["blueprint"] = {}
                bp_store = parsed["blueprint"]
            bp_store["frontend_app"] = frontend_app
    if generate_frontend and frontend_app:
        entry_path = str(frontend_app.get("entry_path") or f"/{mid}")
        extra_files.update(
            {
                "config/frontend_spec.json": _facade().json.dumps(
                    frontend_app, ensure_ascii=False, indent=2
                )
                + "\n",
                "frontend/routes.js": _facade().render_frontend_routes_js(mid, mname, entry_path),
                "frontend/views/HomeView.vue": _facade().render_generated_home_vue(
                    mid, mname, frontend_app
                ),
            }
        )
    try:
        raw_zip = _facade().build_scaffold_zip(mid, mname, manifest, extra_files=extra_files)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
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
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "employees": employees,
        "blueprint": blueprint,
        "frontend_app": frontend_app if generate_frontend else None,
        "had_frontend_fallback": had_frontend_fallback,
    }


def write_mod_suite_industry_card(
    mod_dir: _facade().Path, blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    card = _facade()._mod_suite_industry_card_payload(blueprint)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "industry_card.json").write_text(
        _facade().json.dumps(card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return card


def write_mod_suite_ui_shell(
    mod_dir: _facade().Path, blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    ui_shell = _facade()._mod_suite_ui_shell_payload(blueprint)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "ui_shell.json").write_text(
        _facade().json.dumps(ui_shell, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ui_shell


def _openapi_node_summary(
    db: _facade().Session, workflow_id: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    rows = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.workflow_id == int(workflow_id),
            _facade().WorkflowNode.node_type == "openapi_operation",
        )
        .all()
    )
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for row in rows:
        try:
            cfg = _facade().json.loads(row.config or "{}")
        except _facade().json.JSONDecodeError:
            cfg = {}
        out.append(
            {
                "workflow_id": workflow_id,
                "node_id": row.id,
                "name": row.name,
                "connector_id": int(cfg.get("connector_id") or 0),
                "operation_id": str(cfg.get("operation_id") or ""),
                "needs_configuration": not int(cfg.get("connector_id") or 0)
                or not str(cfg.get("operation_id") or "").strip(),
            }
        )
    return out


async def create_mod_suite_workflows_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    employees: _facade().List[_facade().Dict[str, _facade().Any]],
    brief: str,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    step_message_hook: _facade().Optional[
        _facade().Callable[[str], _facade().Awaitable[None]]
    ] = None,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workflow_mod_link import (
        WorkflowModLinkBody,
        merge_workflow_id_into_existing_entry,
    )
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    api_nodes: _facade().List[_facade().Dict[str, _facade().Any]] = []
    mod_manifest, mod_manifest_err = _facade().read_manifest(mod_dir)
    if mod_manifest_err or not isinstance(mod_manifest, dict):
        mod_manifest = {"id": mod_dir.name}
    n_employees = sum((1 for e in employees if isinstance(e, dict)))
    emp_ord = 0
    for idx, emp in enumerate(employees):
        if not isinstance(emp, dict):
            continue
        try:
            wf_cfg = emp.get("workflow") if isinstance(emp.get("workflow"), dict) else {}
            wf_name = str(
                wf_cfg.get("name") or f"{emp.get('label') or f'员工{idx + 1}'}工作流"
            ).strip()
            wf_desc = str(wf_cfg.get("description") or emp.get("panel_summary") or brief).strip()
            wf = _facade().Workflow(
                user_id=user.id,
                name=(wf_name or f"工作流 {idx + 1}")[:256],
                description=wf_desc[:4000],
                is_active=True,
            )
            db.add(wf)
            db.commit()
            db.refresh(wf)
            emp_ord += 1
            wf_label = str(wf.name or wf_name or f"工作流{emp_ord}")[:256]
            if step_message_hook:
                short = wf_label[:36] + "…" if len(wf_label) > 36 else wf_label
                await step_message_hook(
                    f"第 {emp_ord}/{max(n_employees, 1)} 名员工：已建工作流「{short}」，即将请求模型生成节点与边…"
                )

            async def _nl_status(
                msg: str,
                cur: int = emp_ord,
                tot: int = n_employees,
                wlab: str = wf_label,
            ) -> None:
                if step_message_hook:
                    snippet = wlab[:28] + "…" if len(wlab) > 28 else wlab
                    await step_message_hook(f"第 {cur}/{max(tot, 1)} 名「{snippet}」：{msg}")

            (
                pack_manifest,
                _pack_manifest_err,
            ) = _facade().build_employee_pack_manifest_from_workflow(
                mod_dir.name, mod_manifest, emp, workflow_index=idx
            )
            target_pack_id = str((pack_manifest or {}).get("id") or "").strip()
            target_label = str(
                emp.get("label") or emp.get("panel_title") or target_pack_id or ""
            ).strip()
            nl = await apply_nl_workflow_graph(
                db,
                user,
                workflow_id=wf.id,
                brief=wf_desc or brief,
                provider=provider,
                model=model,
                target_employee_pack_id=target_pack_id or None,
                target_employee_label=target_label or None,
                status_hook=_nl_status if step_message_hook else None,
            )
            link_result = merge_workflow_id_into_existing_entry(
                mod_dir,
                WorkflowModLinkBody(workflow_id=wf.id, workflow_index=idx),
                workflow_name=wf.name,
                workflow_description=wf.description or "",
            )
            wf_api_nodes = _facade()._openapi_node_summary(db, wf.id)
            api_nodes.extend(wf_api_nodes)
            _nl_ok = bool(nl.get("ok", True))
            workflow_results.append(
                {
                    "ok": _nl_ok,
                    "automation_complete": _nl_ok and bool(wf.id),
                    "employee_id": target_pack_id,
                    "workflow_id": wf.id,
                    "workflow_name": wf.name,
                    "workflow_index": idx,
                    "graph": nl,
                    "api_nodes": wf_api_nodes,
                    "manifest_link": link_result,
                }
            )
        except RECOVERABLE_ERRORS as e:
            workflow_results.append(
                {
                    "ok": False,
                    "automation_complete": False,
                    "employee_id": target_pack_id if "target_pack_id" in dir() else "",
                    "workflow_index": idx,
                    "stage": "workflow_binding",
                    "error": str(e)[:1000],
                }
            )
    return {
        "ok": not any((not item.get("ok", True) for item in workflow_results)),
        "workflow_results": workflow_results,
        "api_nodes": api_nodes,
        "api_warnings": [
            f"{n.get('name') or n.get('node_id')} 需要配置 connector_id/operation_id"
            for n in api_nodes
            if n.get("needs_configuration")
        ],
    }


def run_mod_suite_workflow_sandboxes(
    db: _facade().Session,
    user: _facade().User,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workflow_engine import run_workflow_sandbox
    from modstore_server.workflow_sandbox_state import record_workflow_sandbox_run

    reports: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for item in workflow_results:
        wid = item.get("workflow_id") if isinstance(item, dict) else None
        if not wid:
            continue
        report = run_workflow_sandbox(int(wid), {}, mock_employees=True, validate_only=False)
        try:
            record_workflow_sandbox_run(
                db,
                workflow_id=int(wid),
                user_id=user.id,
                report=report,
                validate_only=False,
                mock_employees=True,
            )
        except RECOVERABLE_ERRORS:
            pass
        item["sandbox_report"] = report
        reports.append({"workflow_id": int(wid), "ok": bool(report.get("ok")), "report": report})
    return {
        "ok": all((r.get("ok") for r in reports)) if reports else True,
        "reports": reports,
    }


def write_mod_suite_blueprint(
    mod_dir: _facade().Path,
    blueprint: _facade().Dict[str, _facade().Any],
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    industry_card: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ui_shell: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    api_summary: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    workflow_sandbox: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    employee_readiness: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    vibe_index: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    vibe_heal: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> None:
    data = dict(blueprint)
    if industry_card is not None:
        data["industry_card"] = industry_card
    if ui_shell is not None:
        data["ui_shell"] = ui_shell
    if api_summary is not None:
        data["api_summary"] = api_summary
    if workflow_sandbox is not None:
        data["workflow_sandbox"] = workflow_sandbox
    if employee_readiness is not None:
        data["employee_readiness"] = employee_readiness
    if vibe_index is not None:
        data["vibe_index"] = vibe_index
    if vibe_heal is not None:
        data["vibe_heal"] = vibe_heal
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "ai_blueprint.json").write_text(
        _facade()._suite_blueprint_file(data, workflow_results), encoding="utf-8"
    )


def run_mod_suite_mod_sandbox(
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest

    checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
    data, err = read_manifest(mod_dir)
    checks.append(
        {
            "id": "manifest",
            "ok": not err and bool(data),
            "message": err or "manifest 可读取",
        }
    )
    blueprint_path = mod_dir / "config" / "ai_blueprint.json"
    try:
        blueprint = _facade().json.loads(blueprint_path.read_text(encoding="utf-8"))
        checks.append(
            {
                "id": "blueprint",
                "ok": isinstance(blueprint, dict),
                "message": "ai_blueprint 可读取",
            }
        )
    except RECOVERABLE_ERRORS as e:
        blueprint = {}
        checks.append({"id": "blueprint", "ok": False, "message": str(e)})
    linked_ids = {
        int(x.get("workflow_id"))
        for x in workflow_results
        if isinstance(x, dict) and x.get("workflow_id")
    }
    manifest_entries = data.get("workflow_employees") if isinstance(data, dict) else []
    missing_links: _facade().List[str] = []
    if isinstance(manifest_entries, list):
        for item in manifest_entries:
            if not isinstance(item, dict):
                continue
            wid = item.get("workflow_id")
            if wid and int(wid) not in linked_ids:
                missing_links.append(str(wid))
    checks.append(
        {
            "id": "workflow_links",
            "ok": not missing_links,
            "message": (
                "workflow_employees 已对齐"
                if not missing_links
                else f"未找到工作流: {', '.join(missing_links)}"
            ),
        }
    )
    py_warnings = _facade().mod_compileall_warnings(mod_dir)
    checks.append(
        {
            "id": "python_compile",
            "ok": not py_warnings,
            "message": "Python 路由骨架可编译" if not py_warnings else "；".join(py_warnings),
        }
    )
    return {"ok": all((bool(c.get("ok")) for c in checks)), "checks": checks}
