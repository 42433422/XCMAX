# mypy: disable-error-code="dict-item, index, no-any-return, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_ai_scaffold")


def _merge_traditional_sidebar(
    base: _facade().List[_facade().Dict[str, _facade().Any]], custom: _facade().List[_facade().Any]
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    by_key: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    for item in base:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        by_key[k] = {**item, "key": k}
    for item in custom:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        prev = by_key.get(k, {})
        order = item.get("order")
        if order is None:
            order = prev.get("order")
        by_key[k] = {
            "key": k,
            "label": str(item.get("label") or prev.get("label") or k),
            "path": str(item.get("path") or prev.get("path") or f"/{k}"),
            "visible": item.get("visible", prev.get("visible", True)),
            "order": int(order) if order is not None else int(prev.get("order") or 999),
        }
    out = list(by_key.values())
    out.sort(key=lambda x: int(x.get("order") or 999))
    return out


def _menu_overrides_from_sidebar(
    custom: _facade().List[_facade().Any],
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for item in custom:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        out.append({"key": k, "label": str(item.get("label") or k)})
    return out


def _ensure_suite_manifest_fields(
    manifest: _facade().Dict[str, _facade().Any],
    *,
    industry: _facade().Dict[str, _facade().Any],
    merged_sidebar: _facade().List[_facade().Dict[str, _facade().Any]],
    menu_overrides: _facade().List[_facade().Dict[str, _facade().Any]],
    employees: _facade().List[_facade().Any],
) -> None:
    """就地补全 manifest：与 ``import_mod_suite_repository`` / 校验器期望的结构对齐。"""
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    desc = str(manifest.get("description") or "").strip()
    manifest.setdefault("author", "")
    manifest.setdefault("primary", False)
    manifest.setdefault("dependencies", {"xcagi": ">=1.0.0"})
    manifest.setdefault("backend", {"entry": "blueprints", "init": "mod_init"})
    if not isinstance(manifest.get("backend"), dict):
        manifest["backend"] = {"entry": "blueprints", "init": "mod_init"}
    else:
        be = manifest["backend"]
        be.setdefault("entry", "blueprints")
        be.setdefault("init", "mod_init")
    fe = manifest.get("frontend")
    if not isinstance(fe, dict):
        fe = {}
    menu_raw = fe.get("menu") if isinstance(fe.get("menu"), list) else None
    fe_menu = _facade()._normalize_frontend_menu(menu_raw, mod_id=mid or "mod", mod_name=mname)
    fe.setdefault("routes", "frontend/routes.js")
    fe["menu"] = fe_menu
    fe["menu_overrides"] = menu_overrides
    shell_prev = fe.get("shell") if isinstance(fe.get("shell"), dict) else {}
    fe["shell"] = {**shell_prev, "sidebar_menu": merged_sidebar}
    manifest["frontend"] = fe
    manifest.setdefault("hooks", {})
    manifest.setdefault("comms", {"exports": []})
    if industry:
        manifest["industry"] = dict(industry)
    if not manifest.get("workflow_employees") and employees:
        wf: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for row in employees:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").strip()
            if not eid:
                continue
            wf.append(
                {
                    "id": eid,
                    "label": str(row.get("label") or eid),
                    "panel_title": str(row.get("panel_title") or row.get("label") or eid),
                    "panel_summary": str(row.get("panel_summary") or desc)[:500],
                }
            )
        if wf:
            manifest["workflow_employees"] = wf


def parse_llm_mod_suite_json(
    content: str,
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], str]:
    raw = _facade()._extract_json_text(content)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError as e:
        return (None, f"模型返回非合法 JSON: {e}")
    if not isinstance(data, dict):
        return (None, "JSON 根须为对象")
    blueprint_in = data.get("blueprint") if isinstance(data.get("blueprint"), dict) else {}
    manifest = data.get("manifest")
    if not isinstance(manifest, dict) and isinstance(blueprint_in.get("manifest"), dict):
        manifest = blueprint_in["manifest"]
    if not isinstance(manifest, dict):
        return (None, "缺少 manifest 对象")
    manifest = dict(manifest)
    employees = data.get("employees") if isinstance(data.get("employees"), list) else []
    if not employees and isinstance(blueprint_in.get("employees"), list):
        employees = blueprint_in["employees"]
    industry_top = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    industry_bp = (
        blueprint_in.get("industry") if isinstance(blueprint_in.get("industry"), dict) else {}
    )
    industry = {**industry_bp, **industry_top}
    ui_top = data.get("ui_shell") if isinstance(data.get("ui_shell"), dict) else {}
    ui_bp = blueprint_in.get("ui_shell") if isinstance(blueprint_in.get("ui_shell"), dict) else {}
    ui_shell_in = {**ui_bp, **ui_top}
    custom_sidebar = (
        ui_shell_in["sidebar_menu"] if isinstance(ui_shell_in.get("sidebar_menu"), list) else []
    )
    merged_sidebar = _facade()._merge_traditional_sidebar(
        _facade()._DEFAULT_TRADITIONAL_SIDEBAR, custom_sidebar
    )
    menu_overrides = _facade()._menu_overrides_from_sidebar(custom_sidebar)
    iname = str(industry.get("name") or manifest.get("name") or "通用").strip() or "通用"
    st_in = ui_shell_in.get("settings") if isinstance(ui_shell_in.get("settings"), dict) else {}
    settings_out = {
        "default_industry": str(st_in.get("default_industry") or iname),
        "industry_options": (
            st_in.get("industry_options")
            if isinstance(st_in.get("industry_options"), list) and st_in.get("industry_options")
            else [iname]
        ),
    }
    ui_shell_out = {
        "schema_version": int(ui_shell_in.get("schema_version") or 1),
        "target": str(ui_shell_in.get("target") or "traditional-mode"),
        "mod_id": str(ui_shell_in.get("mod_id") or manifest.get("id") or ""),
        "mod_name": str(ui_shell_in.get("mod_name") or manifest.get("name") or ""),
        "industry": str(ui_shell_in.get("industry") or iname),
        "sidebar_menu": merged_sidebar,
        "menu_overrides": (
            ui_shell_in.get("menu_overrides")
            if isinstance(ui_shell_in.get("menu_overrides"), list)
            else menu_overrides
        ),
        "settings": settings_out,
        "make_scene": (
            ui_shell_in.get("make_scene") if isinstance(ui_shell_in.get("make_scene"), dict) else {}
        ),
    }
    configs = data.get("configs") if isinstance(data.get("configs"), dict) else {}
    if not configs and isinstance(blueprint_in.get("configs"), dict):
        configs = blueprint_in["configs"]
    blueprint: _facade().Dict[str, _facade().Any] = {
        **blueprint_in,
        "manifest": manifest,
        "industry": industry,
        "ui_shell": ui_shell_out,
        "configs": configs,
    }
    _facade()._ensure_suite_manifest_fields(
        manifest,
        industry=industry,
        merged_sidebar=merged_sidebar,
        menu_overrides=menu_overrides,
        employees=employees,
    )
    ve = _facade().validate_manifest_dict(manifest)
    if ve:
        return (None, "manifest 校验: " + "; ".join(ve))
    return ({"manifest": manifest, "employees": employees, "blueprint": blueprint}, "")


def merge_employees_for_blueprint_routes(
    manifest: _facade().Dict[str, _facade().Any],
    employees: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    merged: _facade().List[_facade().Dict[str, _facade().Any]] = []
    seen: set[str] = set()
    for src in manifest.get("workflow_employees") or []:
        if isinstance(src, dict):
            eid = str(src.get("id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                merged.append(dict(src))
    for row in employees:
        if isinstance(row, dict):
            eid = str(row.get("id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                merged.append(dict(row))
    return merged


def render_suite_blueprints_py(
    mod_id: str, mod_name: str, employees: _facade().List[_facade().Dict[str, _facade().Any]]
) -> str:
    from modstore_server.mod_suite_blueprints_template import render_suite_blueprints_py as _render

    return _render(mod_id, mod_name, employees)


def render_frontend_routes_js(mod_id: str, mod_name: str, entry_path: str) -> str:
    ep = (entry_path or f"/{mod_id}").strip() or f"/{mod_id}"
    return f"// auto-generated\nexport default [{{ path: {_facade().json.dumps(ep)}, name: {_facade().json.dumps(mod_name)}, component: () => import('./views/HomeView.vue') }}];\n"


def render_generated_home_vue(
    mod_id: str, mod_name: str, frontend_app: _facade().Dict[str, _facade().Any]
) -> str:
    title = str(frontend_app.get("title") or mod_name)
    return (
        "<template><div class='mod-home'><h1>"
        + _facade().json.dumps(title, ensure_ascii=False)[1:-1]
        + "</h1><p>Mod "
        + mod_id
        + "</p></div></template>\n<script setup lang='ts'></script>\n"
    )


def _normalize_frontend_menu(
    menu_raw: _facade().Optional[_facade().List[_facade().Any]], *, mod_id: str, mod_name: str
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    if isinstance(menu_raw, list) and menu_raw:
        out: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for i, m in enumerate(menu_raw):
            if isinstance(m, dict):
                out.append(
                    {
                        "id": str(m.get("id") or f"{mod_id}-m-{i}"),
                        "label": str(m.get("label") or mod_name),
                        "icon": str(m.get("icon") or "fa-cube"),
                        "path": str(m.get("path") or f"/{mod_id}"),
                    }
                )
        return out
    return [{"id": f"{mod_id}-home", "label": mod_name, "icon": "fa-cube", "path": f"/{mod_id}"}]


def _sanitize_industry(
    industry: _facade().Dict[str, _facade().Any], *, mod_name: str, description: str
) -> _facade().Dict[str, _facade().Any]:
    name = str(industry.get("name") or mod_name or "通用").strip() or "通用"
    return {"schema_version": 1, "name": name, "description": str(description or "")[:500]}


def _normalize_frontend_app(
    raw: _facade().Dict[str, _facade().Any],
    *,
    mod_id: str,
    mod_name: str,
    description: str,
    industry: _facade().Dict[str, _facade().Any],
    employees: _facade().List[_facade().Any],
    frontend_menu: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    base = dict(raw) if isinstance(raw, dict) else {}
    base.setdefault("schema_version", 1)
    base.setdefault("mod_id", mod_id)
    base.setdefault("mod_name", mod_name)
    base.setdefault("title", mod_name)
    base.setdefault("subtitle", description[:240] if description else mod_name)
    base.setdefault("entry_path", f"/{mod_id}")
    base.setdefault("theme", "aurora")
    base.setdefault("industry", str(industry.get("name") or "通用"))
    secs: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for row in employees[:6]:
        if isinstance(row, dict):
            secs.append(
                {
                    "title": str(row.get("label") or row.get("id") or "AI 员工"),
                    "description": str(row.get("panel_summary") or description)[:400],
                    "items": [str(row.get("panel_title") or "自动化")],
                }
            )
    if not secs:
        secs.append(
            {
                "title": "业务驾驶舱",
                "description": description or f"{mod_name} 专业版首页。",
                "items": ["查看能力", "启动流程"],
            }
        )
    base.setdefault("sections", secs)
    base.setdefault(
        "metrics", [{"label": "AI 员工", "value": str(len(secs) or 1), "hint": "workflow"}]
    )
    base.setdefault(
        "hero_actions",
        [
            {"label": "打开专业对话", "kind": "primary", "target": "chat"},
            {"label": "查看工作流", "kind": "secondary", "target": "workflow"},
        ],
    )
    base["frontend_menu"] = frontend_menu
    return base
