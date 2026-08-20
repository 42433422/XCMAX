# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
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

    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
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
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
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
    manifest, perr = _facade().parse_llm_manifest_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出为 manifest"}
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    lib = _facade().modstore_library_path()
    dest_path = lib / mid
    if dest_path.is_dir() and (not replace):
        return {
            "ok": False,
            "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述",
        }
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
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest, validate_manifest_dict

    manifest_warnings: _facade().List[str] = []
    data, err = read_manifest(mod_dir)
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
    blueprint: _facade().Dict[str, _facade().Any],
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
    blueprint: _facade().Dict[str, _facade().Any],
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
            {
                "role": "user",
                "content": f"解析错误：{parse_error}\n\n原始输出：\n{raw[:20000]}",
            },
        ],
        max_tokens=8192,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return (None, result.get("error") or "JSON 修复调用失败", True)
    parsed, perr = _facade().parse_llm_mod_suite_json(str(result.get("content") or ""))
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
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
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
    parsed, perr = _facade().parse_llm_mod_suite_json(raw)
    repair_used = False
    if perr or not parsed:
        parsed, perr, repair_used = await _facade()._repair_mod_suite_json_async(
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
