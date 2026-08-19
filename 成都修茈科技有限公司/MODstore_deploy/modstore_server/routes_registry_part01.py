# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


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
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    shell_from_manifest = frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
    ui_shell = _facade()._read_mod_json_file(
        mod_dir, str(config.get("ui_shell") or "config/ui_shell.json")
    )
    if not ui_shell:
        ui_shell = dict(shell_from_manifest)
    industry_card = _facade()._read_mod_json_file(
        mod_dir, str(config.get("industry_card") or "config/industry_card.json")
    )
    industry = manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
    industry_name = (
        str(
            industry_card.get("name") or industry.get("name") or manifest.get("industry") or "通用"
        ).strip()
        or "通用"
    )
    settings = ui_shell.get("settings") if isinstance(ui_shell.get("settings"), dict) else {}
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
            ui_shell.get("sidebar_menu") if isinstance(ui_shell.get("sidebar_menu"), list) else []
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
    mod_dir: _facade().Path, manifest: _facade().Dict[str, _facade().Any], brief: str = ""
) -> _facade().Dict[str, _facade().Any]:
    mod_id = str(manifest.get("id") or mod_dir.name).strip() or mod_dir.name
    mod_name = str(manifest.get("name") or mod_id).strip() or mod_id
    desc = str(manifest.get("description") or "").strip()
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    blueprint = _facade()._read_mod_json_file(
        mod_dir, str(config.get("ai_blueprint") or "config/ai_blueprint.json")
    )
    spec = blueprint.get("frontend_app") if isinstance(blueprint.get("frontend_app"), dict) else {}
    spec = dict(spec) if isinstance(spec, dict) else {}
    menu = frontend.get("menu") if isinstance(frontend.get("menu"), list) else []
    first_menu = menu[0] if menu and isinstance(menu[0], dict) else {}
    entry_path = (
        str(frontend.get("pro_entry_path") or first_menu.get("path") or f"/{mod_id}").strip()
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
                "description": str(row.get("panel_summary") or row.get("summary") or desc),
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
            "workflow_entry_label": str(spec.get("workflow_entry_label") or "查看工作流"),
            "chat_entry_label": str(spec.get("chat_entry_label") or "打开专业对话"),
        }
    )
    return spec


@_facade().api_router.get("/api/health", tags=["health"], response_model=_facade().HealthResponse)
def health() -> _facade().HealthResponse:
    from modstore_server.deploy_context import health_payload

    return _facade().HealthResponse(ok=True, **health_payload())


@_facade().api_router.get("/api/config", tags=["config"])
def get_config():
    cfg = _facade()._cfg()
    lib = _facade().resolved_library(cfg)
    xc = _facade().resolved_xcagi(cfg)
    st = _facade()._load_state()
    return {
        "library_root": str(lib),
        "xcagi_root": str(xc) if xc else "",
        "library_exists": lib.is_dir(),
        "xcagi_ok": bool(xc and (xc / "mods").is_dir()),
        "saved_library_root": cfg.library_root,
        "saved_xcagi_root": cfg.xcagi_root,
        "saved_xcagi_backend_url": cfg.xcagi_backend_url,
        "xcagi_backend_url": _facade().resolved_xcagi_backend_url(cfg),
        "state": {
            "last_sandbox_mods_root": st.get("last_sandbox_mods_root") or "",
            "last_sandbox_mod_id": st.get("last_sandbox_mod_id") or "",
            "focus_mod_id": st.get("focus_mod_id") or "",
        },
    }


@_facade().api_router.post("/api/export/fhd-shell-mods", tags=["config"])
def api_export_fhd_shell_mods(
    body: _facade().ExportFhdShellDTO = _facade().Body(default_factory=_facade().ExportFhdShellDTO),
):
    fhd = _facade()._fhd_repo_root()
    if not fhd.is_dir():
        raise _facade().HTTPException(
            500, "无法定位 FHD 仓库根目录（预期 MODstore 位于 FHD/MODstore）"
        )
    raw = body.output_path or ""
    raw = raw.strip()
    if raw:
        target = _facade().Path(raw).expanduser().resolve()
    else:
        target = (fhd / "backend" / "shell" / "fhd_shell_mods.json").resolve()
    _facade()._assert_path_inside_fhd_repo(fhd, target)
    lib = _facade()._lib()
    n = _facade().write_fhd_shell_mods_json(lib, target)
    return {"ok": True, "path": str(target), "count": n}


@_facade().api_router.put("/api/config", tags=["config"])
def put_config(body: _facade().ConfigDTO):
    lr = (body.library_root or "").strip()
    xr = (body.xcagi_root or "").strip()
    url = (body.xcagi_backend_url or "").strip()
    cfg = _facade().RepoConfig(
        library_root=str(_facade().Path(lr).expanduser().resolve()) if lr else "",
        xcagi_root=str(_facade().Path(xr).expanduser().resolve()) if xr else "",
        xcagi_backend_url=url,
    )
    _facade().save_config(cfg)
    if cfg.library_root:
        _facade().Path(cfg.library_root).mkdir(parents=True, exist_ok=True)
    return _facade().get_config()


@_facade().api_router.get("/api/mods", tags=["mods"])
def api_list_mods(
    user: _facade().Optional[_facade().User] = _facade().Depends(_facade()._get_optional_user),
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
        (data, err) = _facade().read_manifest(d)
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
        "settings": (selected.get("ui_shell") or {}).get("settings", {}) if selected else {},
        "make_scene": (selected.get("ui_shell") or {}).get("make_scene", {}) if selected else {},
    }


@_facade().api_router.get("/api/mods/{mod_id}", tags=["mods"])
def api_get_mod(mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    (data, err) = _facade().read_manifest(d)
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
                routes = _facade().slim_openapi_paths(spec if isinstance(spec, dict) else {})
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
    (data, err) = _facade().read_manifest(d)
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
        "manifest_backend": data.get("backend") if isinstance(data.get("backend"), dict) else {},
        "manifest_frontend": data.get("frontend") if isinstance(data.get("frontend"), dict) else {},
        "validation_ok": len(ve) == 0,
        "warnings": ve,
        "blueprint_file": bp_file,
        "blueprint_routes": bp_routes,
        "employee_readiness": employee_readiness,
    }


@_facade().api_router.post("/api/mods/{mod_id}/workflow-employees/scaffold", tags=["authoring"])
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


@_facade().api_router.get("/api/mods/{mod_id}/export-employee-pack", tags=["authoring"])
def api_export_workflow_employee_pack(
    mod_id: str,
    workflow_index: int = 0,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    (data, err) = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or workflow_index < 0 or workflow_index >= len(rows):
        raise _facade().HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
    (raw, build_err, pack_id) = _facade().build_employee_pack_zip_from_workflow(
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
    (data, err) = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    idx = int(body.workflow_index)
    if not isinstance(rows, list) or idx < 0 or idx >= len(rows):
        raise _facade().HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
    entry = rows[idx] if isinstance(rows[idx], dict) else {}
    (raw, build_err, pack_id) = _facade().build_employee_pack_zip_from_workflow(
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

    (manifest_zip, manifest_err, _pid) = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if manifest_err or not manifest_zip:
        raise _facade().HTTPException(400, manifest_err or "生成员工包失败")
    from modstore_server.employee_pack_export import build_employee_pack_manifest_from_workflow

    (manifest, manifest_build_err) = build_employee_pack_manifest_from_workflow(
        mod_id, data, entry, workflow_index=idx
    )
    if manifest_build_err or not manifest:
        raise _facade().HTTPException(400, manifest_build_err or "生成员工包 manifest 失败")
    rec: _facade().Dict[str, _facade().Any] = {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "description": str(manifest.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry.strip() or "通用",
        "release_channel": body.release_channel,
        "commerce": {"mode": "free" if body.price <= 0 else "paid", "price": body.price},
        "license": {"type": "personal" if body.price <= 0 else "commercial", "verify_url": None},
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
        except Exception:
            import logging

            logging.getLogger(__name__).exception("EmployeeApplicationService.register_pack failed")
        readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {"ok": True, "package": saved, "audit": audit, "employee_readiness": readiness}


@_facade().api_router.post("/api/mods/{mod_id}/patch-workflow-employee-nodes", tags=["authoring"])
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
    return {"ok": bool(out.get("ok")), "graph_patch": out, "employee_readiness": readiness}


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
    mod_id: str, path: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        p = _facade().resolve_under_mod(d, path)
        text = _facade().read_text_file(p)
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
        p = _facade().resolve_under_mod(d, body.path)
        _facade().write_text_file(p, body.content)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    manifest_warnings: _facade().List[str] = []
    if p.name == "manifest.json" and p.parent.resolve() == d.resolve():
        (data, err) = _facade().read_manifest(d)
        if data and (not err):
            manifest_warnings = _facade().validate_manifest_dict(data)
            fn = _facade().folder_name_must_match_id(d, data)
            if fn:
                manifest_warnings = list(manifest_warnings) + [fn]
    return {"ok": True, "manifest_warnings": manifest_warnings}


@_facade().api_router.post("/api/mods/create", tags=["mods"])
def api_create_mod(
    body: _facade().CreateModDTO, user: _facade().User = _facade().Depends(_facade()._require_user)
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
    except Exception as exc:
        logger.exception("api_mod_ai_scaffold failed")
        raise _facade().HTTPException(500, f"AI 脚手架异常：{exc}") from exc
    if not res.get("ok"):
        raise _facade().HTTPException(400, res.get("error") or "AI 生成 Mod 失败")
    return res
