# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


async def generate_workflow_for_intent(
    db: _facade().Session,
    user: _facade().User,
    *,
    role: str,
    scenario: str,
    workflow_name: str,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    target_employee_pack_id: _facade().Optional[str] = None,
    target_employee_label: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """为 employee_ai_pipeline Stage 2 兜底生成：创建 Workflow 记录 + NL 生图。

    返回 {"ok": True, "workflow_id": int, "name": str} 或 {"ok": False, "error": str}。
    不进行完整沙箱回归（沙箱验证留给用户在工作流页面手动运行），
    但会记录工作流以供 Stage 6 manifest 引用。
    """
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    name = (workflow_name or f"AI 生成工作流 - {role[:20]}")[:256]
    brief_for_nl = f"角色：{role}\n场景：{scenario}" if scenario else role
    wf = _facade().Workflow(
        user_id=user.id, name=name, description=brief_for_nl[:1000], is_active=True
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    nl = await apply_nl_workflow_graph(
        db,
        user,
        workflow_id=wf.id,
        brief=brief_for_nl,
        provider=prov,
        model=mdl,
        target_employee_pack_id=target_employee_pack_id,
        target_employee_label=target_employee_label,
        status_hook=None,
    )
    if not nl.get("ok"):
        return {"ok": False, "error": f"工作流 NL 生图失败: {nl.get('error') or ''}"}
    return {"ok": True, "workflow_id": wf.id, "name": name}


async def run_mod_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    generate_frontend: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """
    生成并导入 Mod。成功: {"ok": True, "id", "path", "manifest"}；
    失败: {"ok": False, "error": "..."}。
    """
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
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
    user_lines = [brief]
    hint = _facade().normalize_mod_id(suggested_id or "")
    if hint:
        user_lines.append(f"作者希望的 manifest.id（若与描述不冲突可采用）: {hint}")
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_lines)},
    ]
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=msgs,
        max_tokens=2048,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    (manifest, perr) = _facade().parse_llm_manifest_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出为 manifest"}
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    lib = _facade().modstore_library_path()
    dest_path = lib / mid
    if dest_path.is_dir() and (not replace):
        return {"ok": False, "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述"}
    try:
        raw_zip = _facade().build_scaffold_zip(mid, mname, manifest)
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
    return {"ok": True, "id": dest.name, "path": str(dest), "manifest": manifest}


def _suite_blueprint_file(
    blueprint: _facade().Dict[str, _facade().Any],
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> str:
    data = dict(blueprint)
    data["workflow_results"] = workflow_results
    return _facade().json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _suite_validation_summary(
    mod_dir: _facade().Path, workflow_results: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest, validate_manifest_dict

    manifest_warnings: _facade().List[str] = []
    (data, err) = read_manifest(mod_dir)
    if err or not data:
        manifest_warnings.append(err or "manifest 无效")
    else:
        manifest_warnings.extend(validate_manifest_dict(data))
    python_warnings = _facade().mod_compileall_warnings(mod_dir)
    workflow_warnings: _facade().List[str] = []
    for item in workflow_results:
        if not isinstance(item, dict):
            continue
        graph = item.get("graph")
        if isinstance(graph, dict):
            if not graph.get("ok", True):
                workflow_warnings.append(str(graph.get("error") or "工作流图生成失败"))
            for err_item in graph.get("validation_errors") or []:
                workflow_warnings.append(str(err_item))
            for warn in graph.get("llm_warnings") or []:
                workflow_warnings.append(str(warn))
        elif item.get("error"):
            workflow_warnings.append(str(item.get("error")))
    repair_suggestions: _facade().List[str] = []
    if manifest_warnings:
        repair_suggestions.append("检查 manifest 字段、目录名与 workflow_employees 结构。")
    if python_warnings:
        repair_suggestions.append("打开 backend/blueprints.py，根据 Python 语法提示修复路由骨架。")
    if workflow_warnings:
        repair_suggestions.append("进入工作流画布检查节点配置、员工 id、知识库或 OpenAPI 参数。")
    return {
        "ok": not (manifest_warnings or python_warnings or workflow_warnings),
        "manifest_warnings": manifest_warnings,
        "python_warnings": python_warnings,
        "workflow_warnings": workflow_warnings,
        "repair_suggestions": repair_suggestions,
    }


def _json_response_format(
    provider: _facade().Optional[str],
) -> _facade().Optional[_facade().Dict[str, str]]:
    if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return {"type": "json_object"}
    return None


def _mod_suite_industry_card_payload(
    blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    industry = blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {}
    manifest = blueprint.get("manifest") if isinstance(blueprint.get("manifest"), dict) else {}
    card: _facade().Dict[str, _facade().Any] = {
        "schema_version": 1,
        "id": str(
            industry.get("id") or industry.get("name") or manifest.get("id") or "通用"
        ).strip()
        or "通用",
        "name": str(industry.get("name") or manifest.get("name") or "通用").strip() or "通用",
        "scenario": str(industry.get("scenario") or manifest.get("description") or "").strip(),
        "description": str(
            industry.get("description")
            or industry.get("scenario")
            or manifest.get("description")
            or ""
        ).strip(),
        "source": "ai_blueprint",
    }
    for key in (
        "units",
        "quantity_fields",
        "product_fields",
        "order_types",
        "intent_keywords",
        "print_config",
        "fields",
        "keywords",
    ):
        value = industry.get(key)
        if value not in (None, "", [], {}):
            card[key] = value
    return card


def _mod_suite_ui_shell_payload(
    blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    manifest = blueprint.get("manifest") if isinstance(blueprint.get("manifest"), dict) else {}
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    frontend_shell = frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
    ui_shell = blueprint.get("ui_shell") if isinstance(blueprint.get("ui_shell"), dict) else {}
    industry = blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {}
    payload: _facade().Dict[str, _facade().Any] = dict(frontend_shell)
    payload.update(ui_shell)
    payload.setdefault("schema_version", 1)
    payload.setdefault("target", "traditional-mode")
    payload.setdefault("mod_id", manifest.get("id") or "")
    payload.setdefault("mod_name", manifest.get("name") or manifest.get("id") or "")
    payload.setdefault("industry", industry.get("name") or "通用")
    payload.setdefault("sidebar_menu", [])
    payload.setdefault(
        "menu_overrides",
        frontend.get("menu_overrides") if isinstance(frontend.get("menu_overrides"), list) else [],
    )
    payload.setdefault(
        "settings",
        {
            "default_industry": industry.get("name") or "通用",
            "industry_options": [industry.get("name") or "通用"],
        },
    )
    payload.setdefault("make_scene", {})
    return payload


def _mod_suite_user_lines(brief: str, suggested_id: _facade().Optional[str]) -> _facade().List[str]:
    user_lines = [brief]
    hint = _facade().normalize_mod_id(suggested_id or "")
    if hint:
        user_lines.append(f"作者希望的 manifest.id（若与描述不冲突可采用）: {hint}")
    return user_lines


async def _repair_mod_suite_json_async(
    prov: str,
    *,
    api_key: str,
    base_url: _facade().Optional[str],
    model: str,
    raw: str,
    parse_error: str,
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], str, bool]:
    repair_prompt = "你是严格 JSON 修复器。用户会提供一个被截断、带多余文字或字符串未闭合的 Mod 蓝图 JSON。请只输出一个合法 JSON 对象，不要 markdown，不要解释。保持原意，缺失字段按最小可用值补全，必须包含 manifest、industry、employees、configs。"
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": f"解析错误：{parse_error}\n\n原始输出：\n{raw[:20000]}"},
        ],
        max_tokens=8192,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return (None, result.get("error") or "JSON 修复调用失败", True)
    (parsed, perr) = _facade().parse_llm_mod_suite_json(str(result.get("content") or ""))
    return (parsed, perr, True)


async def generate_mod_suite_blueprint_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """生成并解析 Mod 套件蓝图；失败时尝试一次 JSON 修复。"""
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
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
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=[
            {"role": "system", "content": _facade().SYSTEM_PROMPT_SUITE},
            {
                "role": "user",
                "content": "\n\n".join(_facade()._mod_suite_user_lines(brief, suggested_id)),
            },
        ],
        max_tokens=8192,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    raw = str(result.get("content") or "")
    (parsed, perr) = _facade().parse_llm_mod_suite_json(raw)
    repair_used = False
    if perr or not parsed:
        (parsed, perr, repair_used) = await _facade()._repair_mod_suite_json_async(
            prov,
            api_key=api_key,
            base_url=base,
            model=mdl,
            raw=raw,
            parse_error=perr or "无法解析模型输出为 Mod 蓝图",
        )
    if perr or not parsed:
        return {
            "ok": False,
            "error": perr or "无法解析模型输出为 Mod 蓝图",
            "raw_content": raw[:4000],
        }
    return {
        "ok": True,
        "provider": prov,
        "model": mdl,
        "parsed": parsed,
        "raw_content": raw[:4000],
        "repair_used": repair_used,
    }


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
        return {"ok": False, "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述"}
    employees_for_routes = _facade().merge_employees_for_blueprint_routes(manifest, employees)
    extra_files = {
        "backend/blueprints.py": _facade().render_suite_blueprints_py(
            mid, mname, employees_for_routes
        ),
        "config/ai_blueprint.json": _facade()._suite_blueprint_file(blueprint, []),
        "config/industry_card.json": _facade().json.dumps(
            _facade()._mod_suite_industry_card_payload(blueprint), ensure_ascii=False, indent=2
        )
        + "\n",
        "config/ui_shell.json": _facade().json.dumps(
            _facade()._mod_suite_ui_shell_payload(blueprint), ensure_ascii=False, indent=2
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
        _facade().json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return card


def write_mod_suite_ui_shell(
    mod_dir: _facade().Path, blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    ui_shell = _facade()._mod_suite_ui_shell_payload(blueprint)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "ui_shell.json").write_text(
        _facade().json.dumps(ui_shell, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    (mod_manifest, mod_manifest_err) = _facade().read_manifest(mod_dir)
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
                msg: str, cur: int = emp_ord, tot: int = n_employees, wlab: str = wf_label
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
        except Exception as e:
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
        except Exception:
            pass
        item["sandbox_report"] = report
        reports.append({"workflow_id": int(wid), "ok": bool(report.get("ok")), "report": report})
    return {"ok": all((r.get("ok") for r in reports)) if reports else True, "reports": reports}


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
    mod_dir: _facade().Path, workflow_results: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest

    checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
    (data, err) = read_manifest(mod_dir)
    checks.append(
        {"id": "manifest", "ok": not err and bool(data), "message": err or "manifest 可读取"}
    )
    blueprint_path = mod_dir / "config" / "ai_blueprint.json"
    try:
        blueprint = _facade().json.loads(blueprint_path.read_text(encoding="utf-8"))
        checks.append(
            {"id": "blueprint", "ok": isinstance(blueprint, dict), "message": "ai_blueprint 可读取"}
        )
    except Exception as e:
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
