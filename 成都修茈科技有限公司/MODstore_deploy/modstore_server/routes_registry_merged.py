"""Auto-merged part* modules (debt24)."""

# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from routes_registry_part01_part01_part01.py ---
"""Implementation extracted from the public facade module."""


def _facade():
    return importlib.import_module("modstore_server.routes_registry")


def _read_mod_json_file(
    mod_dir: _facade().Path, rel_path: str
) -> _facade().Dict[str, _facade().Any]:
    rel = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel.startswith("/") or any((part == ".." for part in rel.split("/"))):
        return {}
    p = mod_dir / rel
    if not p.is_file():
        return {}
    try:
        data = _facade().json.loads(p.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _mod_shell_ui_row(
    mod_dir: _facade().Path, manifest: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    frontend = (
        manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    )
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    shell_from_manifest = (
        frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
    )
    ui_shell = _facade()._read_mod_json_file(
        mod_dir, str(config.get("ui_shell") or "config/ui_shell.json")
    )
    if not ui_shell:
        ui_shell = dict(shell_from_manifest)
    industry_card = _facade()._read_mod_json_file(
        mod_dir, str(config.get("industry_card") or "config/industry_card.json")
    )
    industry = (
        manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
    )
    industry_name = (
        str(
            industry_card.get("name")
            or industry.get("name")
            or manifest.get("industry")
            or "通用"
        ).strip()
        or "通用"
    )
    settings = (
        ui_shell.get("settings") if isinstance(ui_shell.get("settings"), dict) else {}
    )
    raw_options = (
        settings.get("industry_options")
        if isinstance(settings.get("industry_options"), list)
        else []
    )
    industry_options: _facade().List[str] = []
    for raw in [industry_name, *raw_options]:
        text = str(raw or "").strip()
        if text and text not in industry_options:
            industry_options.append(text)
    return {
        "id": manifest.get("id") or mod_dir.name,
        "name": manifest.get("name") or mod_dir.name,
        "primary": bool(manifest.get("primary")),
        "frontend": frontend,
        "industry": industry,
        "industry_card": industry_card or {"schema_version": 1, "name": industry_name},
        "ui_shell": ui_shell,
        "sidebar_menu": (
            ui_shell.get("sidebar_menu")
            if isinstance(ui_shell.get("sidebar_menu"), list)
            else []
        ),
        "menu_overrides": (
            ui_shell.get("menu_overrides")
            if isinstance(ui_shell.get("menu_overrides"), list)
            else (
                frontend.get("menu_overrides")
                if isinstance(frontend.get("menu_overrides"), list)
                else []
            )
        ),
        "industry_options": industry_options or ["通用"],
        "config_paths": {
            "industry_card": config.get("industry_card") or "config/industry_card.json",
            "ui_shell": config.get("ui_shell") or "config/ui_shell.json",
        },
    }


def _frontend_spec_for_existing_mod(
    mod_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    brief: str = "",
) -> _facade().Dict[str, _facade().Any]:
    mod_id = str(manifest.get("id") or mod_dir.name).strip() or mod_dir.name
    mod_name = str(manifest.get("name") or mod_id).strip() or mod_id
    desc = str(manifest.get("description") or "").strip()
    frontend = (
        manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    )
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    blueprint = _facade()._read_mod_json_file(
        mod_dir, str(config.get("ai_blueprint") or "config/ai_blueprint.json")
    )
    spec = (
        blueprint.get("frontend_app")
        if isinstance(blueprint.get("frontend_app"), dict)
        else {}
    )
    spec = dict(spec) if isinstance(spec, dict) else {}
    menu = frontend.get("menu") if isinstance(frontend.get("menu"), list) else []
    first_menu = menu[0] if menu and isinstance(menu[0], dict) else {}
    entry_path = (
        str(
            frontend.get("pro_entry_path") or first_menu.get("path") or f"/{mod_id}"
        ).strip()
        or f"/{mod_id}"
    )
    subtitle = str(brief or "").strip() or str(spec.get("subtitle") or desc).strip()
    employees = (
        manifest.get("workflow_employees")
        if isinstance(manifest.get("workflow_employees"), list)
        else []
    )
    if not isinstance(spec.get("sections"), list) or not spec.get("sections"):
        spec["sections"] = [
            {
                "title": str(row.get("label") or row.get("id") or "AI 员工"),
                "description": str(
                    row.get("panel_summary") or row.get("summary") or desc
                ),
                "items": [str(row.get("panel_title") or "自动化业务处理")],
            }
            for row in employees[:4]
            if isinstance(row, dict)
        ] or [
            {
                "title": "业务驾驶舱",
                "description": desc or "面向本 Mod 的专业版首页。",
                "items": ["查看能力", "启动流程", "沉淀业务配置"],
            }
        ]
    if not isinstance(spec.get("metrics"), list) or not spec.get("metrics"):
        spec["metrics"] = [
            {
                "label": "AI 员工",
                "value": str(len(employees) or 1),
                "hint": "来自 manifest.workflow_employees",
            },
            {"label": "前端入口", "value": "1", "hint": entry_path},
        ]
    if not isinstance(spec.get("hero_actions"), list) or not spec.get("hero_actions"):
        spec["hero_actions"] = [
            {"label": "打开专业对话", "kind": "primary", "target": "chat"},
            {"label": "查看工作流", "kind": "secondary", "target": "workflow"},
        ]
    manifest_industry = (
        manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
    )
    industry_name = str(spec.get("industry") or manifest_industry.get("name") or "通用")
    spec.update(
        {
            "schema_version": 1,
            "mod_id": mod_id,
            "mod_name": mod_name,
            "entry_path": entry_path,
            "title": str(spec.get("title") or mod_name),
            "subtitle": subtitle or desc or f"{mod_name} 专业版前端",
            "theme": str(spec.get("theme") or "aurora"),
            "industry": industry_name,
            "workflow_entry_label": str(
                spec.get("workflow_entry_label") or "查看工作流"
            ),
            "chat_entry_label": str(spec.get("chat_entry_label") or "打开专业对话"),
        }
    )
    return spec


@_facade().api_router.get(
    "/api/health", tags=["health"], response_model=_facade().HealthResponse
)
def health() -> _facade().HealthResponse:
    from modstore_server.deploy_context import health_payload

    return _facade().HealthResponse(ok=True, **health_payload())


@_facade().api_router.get("/api/mods", tags=["mods"])
def api_list_mods(
    user: _facade().Optional[_facade().User] = _facade().Depends(
        _facade()._get_optional_user
    ),
):
    lib = _facade()._lib()
    if user is None:
        rows = []
    elif user.is_admin:
        rows = _facade().list_mods(lib)
    else:
        user_mod_ids = _facade().get_user_mod_ids(user.id)
        all_rows = _facade().list_mods(lib)
        rows = [r for r in all_rows if r.get("id") in user_mod_ids]
    return {"data": rows}


@_facade().api_router.get("/api/mods/shell-ui", tags=["mods"])
def api_mods_shell_ui(mod_id: str = ""):
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for d in _facade().iter_mod_dirs(_facade()._lib()):
        data, err = _facade().read_manifest(d)
        if err or not data:
            continue
        rows.append(_facade()._mod_shell_ui_row(d, data))
    selected = None
    wanted = str(mod_id or "").strip()
    if wanted:
        selected = next((row for row in rows if row.get("id") == wanted), None)
    if selected is None:
        selected = next((row for row in rows if row.get("primary")), None)
    if selected is None and rows:
        selected = rows[0]
    industry_options: _facade().List[str] = []
    for row in rows:
        for raw in row.get("industry_options") or []:
            text = str(raw or "").strip()
            if text and text not in industry_options:
                industry_options.append(text)
    return {
        "ok": True,
        "selected_mod_id": selected.get("id") if selected else "",
        "mods": rows,
        "industry_options": industry_options or ["通用"],
        "sidebar_menu": selected.get("sidebar_menu") if selected else [],
        "menu_overrides": selected.get("menu_overrides") if selected else [],
        "settings": (selected.get("ui_shell") or {}).get("settings", {})
        if selected
        else {},
        "make_scene": (selected.get("ui_shell") or {}).get("make_scene", {})
        if selected
        else {},
    }


@_facade().api_router.get("/api/mods/{mod_id}", tags=["mods"])
def api_get_mod(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    ve = _facade().validate_manifest_dict(data)
    fn = _facade().folder_name_must_match_id(d, data)
    if fn:
        ve = list(ve) + [fn]
    files = _facade().list_mod_relative_files(d)
    sf = _facade().get_session_factory()
    with sf() as db:
        employee_readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "id": mod_id,
        "manifest": data,
        "validation_ok": len(ve) == 0,
        "warnings": ve,
        "files": files,
        "employee_readiness": employee_readiness,
    }


@_facade().api_router.get("/api/authoring/extension-surface", tags=["authoring"])
def api_authoring_extension_surface(merge_host: bool = False):
    bundled = _facade().load_bundled_extension_surface()
    result: _facade().Dict[str, _facade().Any] = {
        "ok": True,
        "bundled": bundled,
        "host_openapi": None,
        "host_openapi_error": None,
    }
    if merge_host:
        cfg = _facade()._cfg()
        base = _facade().resolved_xcagi_backend_url(cfg).rstrip("/")
        url = f"{base}/openapi.json"
        try:
            with _facade().httpx.Client(timeout=20.0) as client:
                r = client.get(url)
            if r.status_code >= 400:
                result["host_openapi_error"] = f"HTTP {r.status_code} from {url}"
            else:
                spec = r.json()
                routes = _facade().slim_openapi_paths(
                    spec if isinstance(spec, dict) else {}
                )
                result["host_openapi"] = {
                    "base_url": base,
                    "openapi_url": url,
                    "route_count": len(routes),
                    "routes": routes,
                }
        except _facade().httpx.RequestError as e:
            result["host_openapi_error"] = f"{type(e).__name__}: {e} ({url})"
        except _facade().json.JSONDecodeError as e:
            result["host_openapi_error"] = f"openapi.json 非 JSON: {e}"
    return result


@_facade().api_router.get("/api/mods/{mod_id}/blueprint-routes", tags=["authoring"])
def api_mod_blueprint_routes(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    for rel in ("backend/blueprints.py", "blueprints.py"):
        p = d / rel
        if p.is_file():
            routes = _facade().scan_fastapi_router_routes(p)
            return {"ok": True, "file": rel, "routes": routes}
    return {
        "ok": True,
        "file": None,
        "routes": [],
        "hint": "未找到 backend/blueprints.py 或根目录 blueprints.py（FastAPI 路由扫描）",
    }


@_facade().api_router.get("/api/mods/{mod_id}/authoring-summary", tags=["authoring"])
def api_mod_authoring_summary(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    ve = _facade().validate_manifest_dict(data)
    fn = _facade().folder_name_must_match_id(d, data)
    if fn:
        ve = list(ve) + [fn]
    bp_file: str | None = None
    bp_routes: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for rel in ("backend/blueprints.py", "blueprints.py"):
        p = d / rel
        if p.is_file():
            bp_file = rel
            bp_routes = _facade().scan_fastapi_router_routes(p)
            break
    sf = _facade().get_session_factory()
    with sf() as db:
        employee_readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "ok": True,
        "id": mod_id,
        "manifest_backend": data.get("backend")
        if isinstance(data.get("backend"), dict)
        else {},
        "manifest_frontend": data.get("frontend")
        if isinstance(data.get("frontend"), dict)
        else {},
        "validation_ok": len(ve) == 0,
        "warnings": ve,
        "blueprint_file": bp_file,
        "blueprint_routes": bp_routes,
        "employee_readiness": employee_readiness,
    }


@_facade().api_router.post(
    "/api/mods/{mod_id}/workflow-employees/scaffold", tags=["authoring"]
)
def api_mod_workflow_employee_scaffold(
    mod_id: str,
    body: _facade().WorkflowEmployeeScaffoldDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        return _facade().run_workflow_employee_scaffold(
            d, body, allow_blueprint_merge=_facade().scaffold_auto_merge_default()
        )
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e


# --- from routes_registry_part01_part01_part02.py ---
"""Implementation extracted from the public facade module."""


@_facade().api_router.get("/api/mods/{mod_id}/export-employee-pack", tags=["authoring"])
def api_export_workflow_employee_pack(
    mod_id: str,
    workflow_index: int = 0,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or workflow_index < 0 or workflow_index >= len(rows):
        raise _facade().HTTPException(
            400, "workflow_index 越界或 workflow_employees 非数组"
        )
    raw, build_err, pack_id = _facade().build_employee_pack_zip_from_workflow(
        mod_id,
        data,
        rows[workflow_index] if isinstance(rows[workflow_index], dict) else {},
        workflow_index=workflow_index,
        mod_dir=d,
    )
    if build_err or not raw or (not pack_id):
        raise _facade().HTTPException(400, build_err or "生成员工包失败")
    return _facade().StreamingResponse(
        _facade().io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pack_id}.xcemp"'},
    )


@_facade().api_router.post(
    "/api/mods/{mod_id}/register-workflow-employee-catalog", tags=["authoring"]
)
async def api_register_workflow_employee_catalog(
    mod_id: str,
    body: _facade().WorkflowEmployeeCatalogDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    idx = int(body.workflow_index)
    if not isinstance(rows, list) or idx < 0 or idx >= len(rows):
        raise _facade().HTTPException(
            400, "workflow_index 越界或 workflow_employees 非数组"
        )
    entry = rows[idx] if isinstance(rows[idx], dict) else {}
    raw, build_err, pack_id = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if build_err or not raw or (not pack_id):
        raise _facade().HTTPException(400, build_err or "生成员工包失败")
    audit = await _facade().run_package_audit_async(raw, {"artifact": "employee_pack"})
    if not audit.get("ok"):
        raise _facade().HTTPException(400, str(audit.get("error") or "包审核失败"))
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    if summary and summary.get("pass") is False:
        raise _facade().HTTPException(400, "五维审核未通过，禁止登记")
    import tempfile

    from modstore_server.catalog_store import append_package
    from modstore_server.models import CatalogItem

    manifest_zip, manifest_err, _pid = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if manifest_err or not manifest_zip:
        raise _facade().HTTPException(400, manifest_err or "生成员工包失败")
    from modstore_server.employee_pack_export import (
        build_employee_pack_manifest_from_workflow,
    )

    manifest, manifest_build_err = build_employee_pack_manifest_from_workflow(
        mod_id, data, entry, workflow_index=idx
    )
    if manifest_build_err or not manifest:
        raise _facade().HTTPException(
            400, manifest_build_err or "生成员工包 manifest 失败"
        )
    rec: _facade().Dict[str, _facade().Any] = {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "description": str(manifest.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry.strip() or "通用",
        "release_channel": body.release_channel,
        "commerce": {
            "mode": "free" if body.price <= 0 else "paid",
            "price": body.price,
        },
        "license": {
            "type": "personal" if body.price <= 0 else "commercial",
            "verify_url": None,
        },
        "probe_mod_id": mod_id,
    }
    with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(manifest_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        saved = append_package(rec, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    sf = _facade().get_session_factory()
    with sf() as db:
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if not row:
            row = CatalogItem(pkg_id=pack_id, author_id=user.id)
            db.add(row)
        row.version = saved.get("version") or rec["version"]
        row.name = saved.get("name") or rec["name"]
        row.description = saved.get("description") or rec["description"]
        row.price = float(body.price or 0)
        row.artifact = "employee_pack"
        row.industry = saved.get("industry") or rec["industry"]
        row.stored_filename = saved.get("stored_filename") or ""
        row.sha256 = saved.get("sha256") or ""
        db.commit()
        try:
            from modstore_server.application.employee import (
                get_default_employee_application_service,
            )

            get_default_employee_application_service().register_pack(
                author_id=user.id,
                mod_id=mod_id,
                pack_id=pack_id,
                version=saved.get("version") or rec["version"],
            )
        except RECOVERABLE_ERRORS:
            import logging

            logging.getLogger(__name__).exception(
                "EmployeeApplicationService.register_pack failed"
            )
        readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "ok": True,
        "package": saved,
        "audit": audit,
        "employee_readiness": readiness,
    }


@_facade().api_router.post(
    "/api/mods/{mod_id}/patch-workflow-employee-nodes", tags=["authoring"]
)
def api_patch_workflow_employee_nodes(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    sf = _facade().get_session_factory()
    with sf() as db:
        out = _facade().patch_workflow_graph_employee_nodes(
            db, user, mod_dir=d, workflow_results=[]
        )
        readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "ok": bool(out.get("ok")),
        "graph_patch": out,
        "employee_readiness": readiness,
    }


@_facade().api_router.put("/api/mods/{mod_id}/manifest", tags=["mods"])
def api_put_manifest(
    mod_id: str,
    body: _facade().ManifestPutDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        warnings = _facade().save_manifest_validated(d, body.manifest)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "warnings": warnings}


@_facade().api_router.get("/api/mods/{mod_id}/file", tags=["mods"])
def api_get_mod_file(
    mod_id: str,
    path: str,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        text = _facade().read_text_under_mod(d, path)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    return {"path": path.replace("\\", "/").lstrip("/"), "content": text}


@_facade().api_router.put("/api/mods/{mod_id}/file", tags=["mods"])
def api_put_mod_file(
    mod_id: str,
    body: _facade().ModFilePutDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        p = _facade().write_text_under_mod(d, body.path, body.content)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    manifest_warnings: _facade().List[str] = []
    if p.name == "manifest.json" and p.parent.resolve() == d.resolve():
        data, err = _facade().read_manifest(d)
        if data and (not err):
            manifest_warnings = _facade().validate_manifest_dict(data)
            fn = _facade().folder_name_must_match_id(d, data)
            if fn:
                manifest_warnings = list(manifest_warnings) + [fn]
    return {"ok": True, "manifest_warnings": manifest_warnings}


@_facade().api_router.post("/api/mods/create", tags=["mods"])
def api_create_mod(
    body: _facade().CreateModDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    mid = body.mod_id.strip().lower().replace(" ", "-")
    try:
        dest = _facade().create_mod(mid, body.display_name.strip(), _facade()._lib())
        _facade().apply_industry_to_mod_dir(dest, (body.industry_id or "通用").strip())
    except FileExistsError as e:
        raise _facade().HTTPException(409, str(e)) from e
    except (FileNotFoundError, ValueError) as e:
        raise _facade().HTTPException(400, str(e)) from e
    _facade().add_user_mod(user.id, mid)
    return {
        "ok": True,
        "path": str(dest),
        "id": mid,
        "industry_id": (body.industry_id or "通用").strip(),
    }


@_facade().api_router.post("/api/mods/ai-scaffold", tags=["mods"])
async def api_mod_ai_scaffold(
    body: _facade().ModAiScaffoldDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    import logging

    logger = logging.getLogger(__name__)
    sf = _facade().get_session_factory()
    try:
        with sf() as db:
            res = await _facade().run_mod_suite_ai_scaffold_async(
                db,
                user,
                brief=body.brief,
                suggested_id=body.suggested_id,
                replace=body.replace,
                industry_id=body.industry_id,
                provider=body.provider,
                model=body.model,
                manifest_override=body.manifest_override,
            )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("api_mod_ai_scaffold failed")
        raise _facade().HTTPException(500, f"AI 脚手架异常：{exc}") from exc
    if not res.get("ok"):
        raise _facade().HTTPException(400, res.get("error") or "AI 生成 Mod 失败")
    return res


# --- from routes_registry_part02.py ---
"""Implementation extracted from the public facade module."""


@_facade().api_router.post("/api/mods/{mod_id}/frontend/regenerate", tags=["authoring"])
def api_mod_frontend_regenerate(
    mod_id: str,
    body: _facade().FrontendRegenerateDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    mod_dir = _facade()._mod_dir(mod_id)
    manifest, err = _facade().read_manifest(mod_dir)
    if not manifest or err:
        raise _facade().HTTPException(400, err or "无法读取 manifest")
    try:
        snap = _facade().capture_manifest_snapshot(
            mod_dir, f"重新生成前端前 {_facade().time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except RECOVERABLE_ERRORS:
        snap = None
    spec = _facade()._frontend_spec_for_existing_mod(mod_dir, manifest, body.brief)
    mod_name = str(manifest.get("name") or mod_id)
    frontend = (
        manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    )
    menu = (
        frontend.get("menu")
        if isinstance(frontend.get("menu"), list) and frontend.get("menu")
        else [
            {
                "id": f"{mod_id}-home",
                "label": mod_name,
                "icon": "fa-cube",
                "path": spec["entry_path"],
            }
        ]
    )
    frontend.update(
        {
            "routes": frontend.get("routes") or "frontend/routes",
            "menu": menu,
            "pro_entry_path": spec["entry_path"],
            "app": "config/frontend_spec.json",
        }
    )
    manifest["frontend"] = frontend
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    config["frontend_spec"] = "config/frontend_spec.json"
    manifest["config"] = config
    warnings = _facade().save_manifest_validated(mod_dir, manifest)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "frontend" / "views").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "frontend_spec.json").write_text(
        _facade().json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (mod_dir / "frontend" / "routes.js").write_text(
        _facade().render_frontend_routes_js(mod_id, mod_name, spec["entry_path"]),
        encoding="utf-8",
    )
    (mod_dir / "frontend" / "views" / "HomeView.vue").write_text(
        _facade().render_generated_home_vue(mod_id, mod_name, spec), encoding="utf-8"
    )
    return {
        "ok": True,
        "frontend_spec": spec,
        "entry_path": spec["entry_path"],
        "snapshot": snap,
        "manifest_warnings": warnings,
        "files": [
            "config/frontend_spec.json",
            "frontend/routes.js",
            "frontend/views/HomeView.vue",
        ],
    }


@_facade().api_router.delete("/api/mods/{mod_id}", tags=["mods"])
def api_delete_mod(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    mid = mod_id.strip()
    _facade()._assert_user_owns_mod(user, mid)
    try:
        _facade().remove_mod_by_manifest_id(_facade()._lib(), mid)
    except FileNotFoundError:
        raise _facade().HTTPException(404, "不存在") from None
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    _facade().remove_user_mod(user.id, mid)
    return {"ok": True}


@_facade().api_router.post("/api/mods/import", tags=["mods"])
async def api_import_mod(
    file: _facade().UploadFile = _facade().File(...),
    replace: bool = True,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise _facade().HTTPException(400, "请上传 .zip")
    raw = await file.read()
    max_bytes = int(
        _facade().os.environ.get(
            "MODSTORE_CATALOG_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024)
        )
    )
    if len(raw) > max_bytes:
        raise _facade().HTTPException(
            400, f"文件过大（>{max_bytes // 1024 // 1024}MB）"
        )
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, _facade()._lib(), replace=replace)
    except (ValueError, FileExistsError) as e:
        raise _facade().HTTPException(400, str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)
    _facade().add_user_mod(user.id, dest.name)
    return {"ok": True, "id": dest.name, "path": str(dest)}


@_facade().api_router.get("/api/mods/{mod_id}/export", tags=["mods"])
def api_export_mod(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    buf = _facade().io.BytesIO()
    with _facade().zipfile.ZipFile(buf, "w", _facade().zipfile.ZIP_DEFLATED) as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(d).as_posix())
    buf.seek(0)
    return _facade().StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{mod_id}.zip"'},
    )


@_facade().api_router.post("/api/sync/push", tags=["sync"])
def api_sync_push(
    body: _facade().SyncDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    cfg = _facade()._cfg()
    xc = _facade().resolved_xcagi(cfg)
    if not xc:
        raise _facade().HTTPException(
            400,
            "未配置有效的 XCAGI 根目录（Mod 源码库页「路径与同步」或环境变量 XCAGI_ROOT）",
        )
    if not user.is_admin and body.mod_ids:
        for mod_id in body.mod_ids:
            _facade()._assert_user_owns_mod(user, mod_id)
    lib = _facade()._lib()
    try:
        done = _facade().deploy_to_xcagi(body.mod_ids, lib, xc, replace=True)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "deployed": done}


@_facade().api_router.post("/api/sync/pull", tags=["sync"])
def api_sync_pull(
    body: _facade().SyncDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    cfg = _facade()._cfg()
    xc = _facade().resolved_xcagi(cfg)
    if not xc:
        raise _facade().HTTPException(400, "未配置有效的 XCAGI 根目录")
    lib = _facade()._lib()
    try:
        done = _facade().pull_from_xcagi(body.mod_ids, lib, xc, replace=True)
    except FileNotFoundError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileExistsError as e:
        raise _facade().HTTPException(409, str(e)) from e
    return {"ok": True, "pulled": done}


@_facade().api_router.post("/api/debug/sandbox", tags=["debug"])
def api_debug_sandbox(
    body: _facade().SandboxDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, body.mod_id)
    mod_id = body.mod_id.strip()
    _facade()._mod_dir(mod_id)
    lib = _facade()._lib()
    src = (lib / mod_id).resolve()
    root = _facade().project_root()
    sand = root / "debug_sandbox"
    sand.mkdir(parents=True, exist_ok=True)
    session = _facade().uuid.uuid4().hex[:12]
    mods_root = (sand / session / "mods").resolve()
    mods_root.mkdir(parents=True, exist_ok=True)
    dst = mods_root / mod_id
    if dst.exists():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            _facade().shutil.rmtree(dst)
    try:
        if body.mode == "symlink":
            try:
                _facade().os.symlink(src, dst, target_is_directory=True)
            except OSError:
                _facade().shutil.copytree(src, dst)
        else:
            _facade().shutil.copytree(src, dst)
    except OSError as e:
        raise _facade().HTTPException(500, f"创建沙箱失败: {e}") from e
    path_str = str(mods_root)
    _facade()._save_state(
        {
            "last_sandbox_mods_root": path_str,
            "last_sandbox_mod_id": mod_id,
            "last_sandbox_session": session,
        }
    )
    return {
        "ok": True,
        "session": session,
        "mods_root": path_str,
        "mod_id": mod_id,
        "xcagi_mods_root_env": f"XCAGI_MODS_ROOT={path_str}",
        "hint": "重启 XCAGI 后端后，仅会从此目录加载 Mod。",
    }


@_facade().api_router.post("/api/debug/focus-primary", tags=["debug"])
def api_debug_focus_primary(
    body: _facade().FocusPrimaryDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, body.mod_id)
    target = body.mod_id.strip()
    _facade()._mod_dir(target)
    lib = _facade()._lib()
    updated: _facade().List[str] = []
    for d in _facade().iter_mod_dirs(lib):
        data, err = _facade().read_manifest(d)
        if err or not data:
            continue
        mid = (data.get("id") or d.name).strip()
        data["primary"] = mid == target
        try:
            _facade().write_manifest(d, data)
            updated.append(mid)
        except OSError as e:
            raise _facade().HTTPException(500, f"写入失败 {d.name}: {e}") from e
    _facade()._save_state({"focus_mod_id": target})
    return {"ok": True, "primary_mod_id": target, "updated_manifests": updated}


@_facade().api_router.get("/api/fhd/db-tokens/status", tags=["debug"])
def api_fhd_db_tokens_status():
    cfg = _facade()._cfg()
    base = _facade().resolved_xcagi_backend_url(cfg).rstrip("/")
    url = f"{base}/api/fhd/db-tokens/status"
    try:
        with _facade().httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except _facade().httpx.RequestError as e:
        return {"ok": False, "error": str(e), "url": url, "data": None}
    try:
        payload = r.json()
    except _facade().json.JSONDecodeError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {
        "ok": ok,
        "status_code": r.status_code,
        "url": url,
        "data": payload if ok else None,
        "error": None if ok else (r.text or str(payload))[:500],
    }


@_facade().api_router.get("/api/xcagi/loading-status", tags=["debug"])
def api_xcagi_loading_status():
    cfg = _facade()._cfg()
    base = _facade().resolved_xcagi_backend_url(cfg)
    url = f"{base}/api/mods/loading-status"
    try:
        with _facade().httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except _facade().httpx.RequestError as e:
        return {"ok": False, "error": str(e), "url": url, "data": None}
    try:
        payload = r.json()
    except _facade().json.JSONDecodeError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {"ok": ok, "status_code": r.status_code, "url": url, "data": payload}


@_facade().api_router.get("/api/xcagi/installed-mods", tags=["sync"])
def api_xcagi_installed_mods():
    cfg = _facade()._cfg()
    xc = _facade().resolved_xcagi(cfg)
    if not xc:
        return {
            "ok": False,
            "error": "未配置有效的 XCAGI 根目录（「路径与同步」或环境变量）",
            "mods_path": "",
            "mods": [],
            "primary_mod": None,
            "primary_mod_count": 0,
        }
    mods_dir = (xc / "mods").resolve()
    if not mods_dir.is_dir():
        return {
            "ok": True,
            "mods_path": str(mods_dir),
            "mods": [],
            "note": "XCAGI/mods 目录尚不存在",
            "primary_mod": None,
            "primary_mod_count": 0,
        }
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for d in _facade().iter_mod_dirs(mods_dir):
        data, err = _facade().read_manifest(d)
        if err or not data:
            rows.append(
                {
                    "id": d.name,
                    "name": "",
                    "version": "",
                    "primary": False,
                    "ok": False,
                    "error": err or "manifest 无效",
                }
            )
            continue
        rows.append(
            {
                "id": str(data.get("id") or d.name).strip() or d.name,
                "name": str(data.get("name") or "").strip(),
                "version": str(data.get("version") or "").strip(),
                "primary": bool(data.get("primary")),
                "ok": True,
            }
        )
    rows.sort(key=lambda r: str(r.get("id") or ""))
    primary_rows = [r for r in rows if r.get("primary") and r.get("ok") is not False]
    primary_mod = primary_rows[0] if len(primary_rows) == 1 else None
    return {
        "ok": True,
        "mods_path": str(mods_dir),
        "mods": rows,
        "primary_mod": primary_mod,
        "primary_mod_count": len(primary_rows),
    }


def _include_optional(app: _facade().FastAPI, module_path: str) -> None:
    try:
        mod = __import__(module_path, fromlist=["router"])
    except ImportError as exc:
        _facade().logging.getLogger(__name__).info(
            "skip optional router %s: %s", module_path, exc
        )
        return
    except RECOVERABLE_ERRORS:
        _facade().logging.getLogger(__name__).exception(
            "FATAL: router %s failed to load", module_path
        )
        raise
    router = getattr(mod, "router", None)
    if router is None:
        return
    app.include_router(router)
    hooks = getattr(mod, "workflow_hooks_router", None)
    if hooks is not None:
        app.include_router(hooks)


# --- from routes_registry_part03.py ---
"""Implementation extracted from the public facade module."""


def _maybe_mount_dev_docs(app: _facade().FastAPI) -> None:
    docs_root = _facade().Path(__file__).resolve().parent.parent / "docs"
    if not docs_root.is_dir():
        return
    app.mount(
        "/dev-docs", _facade().StaticFiles(directory=str(docs_root)), name="dev-docs"
    )


def _maybe_mount_ui(app: _facade().FastAPI) -> None:
    root = _facade().Path(__file__).resolve().parent.parent
    dist = root / "web" / "dist"
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount(
            "/assets", _facade().StaticFiles(directory=str(assets)), name="ui-assets"
        )
    index_file = dist / "index.html"

    @app.get("/")
    def ui_root():
        if index_file.is_file():
            return _facade().FileResponse(index_file)
        raise _facade().HTTPException(404)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if (
            full_path.startswith("api")
            or full_path.startswith("v1")
            or full_path.startswith("docs")
            or full_path.startswith("dev-docs")
            or full_path.startswith("redoc")
            or full_path.startswith("market")
            or (full_path == "openapi.json")
        ):
            raise _facade().HTTPException(404)
        if index_file.is_file():
            return _facade().FileResponse(index_file)
        raise _facade().HTTPException(404)


def register_all_routes(app: _facade().FastAPI) -> None:
    from modstore_server.api.market_routes import router as market_router
    from modstore_server.api.payment_routes import router as payment_router

    app.include_router(market_router)
    app.include_router(payment_router)
    from modstore_server.api.catalog_public_routes import (
        router as catalog_public_router,
    )
    from modstore_server.mod_sync_catalog_api import router as mod_sync_catalog_router

    app.include_router(catalog_public_router)
    app.include_router(mod_sync_catalog_router)
    app.include_router(_facade().api_router)
    for _m in _facade()._OPTIONAL_MODULES:
        _facade()._include_optional(app, _m)
    _facade()._maybe_mount_dev_docs(app)
    _facade()._maybe_mount_ui(app)
