from __future__ import annotations

import io
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from modman.blueprint_scan import scan_fastapi_router_routes
from modman.fhd_shell_export import write_fhd_shell_mods_json
from modman.industry_presets import apply_industry_to_mod_dir
from modman.manifest_util import (
    folder_name_must_match_id,
    read_manifest,
    save_manifest_validated,
    validate_manifest_dict,
    write_manifest,
)
from modman.repo_config import (
    RepoConfig,
    resolved_library,
    resolved_xcagi,
    resolved_xcagi_backend_url,
    save_config,
)
from modman.scaffold import create_mod
from modman.store import (
    deploy_to_xcagi,
    import_zip,
    iter_mod_dirs,
    list_mod_relative_files,
    list_mods,
    project_root,
    pull_from_xcagi,
    remove_mod,
    remove_mod_by_manifest_id,
)
from modman.surface_bundle import load_bundled_extension_surface
from modstore_server.api.auth_deps import assert_user_owns_mod as _assert_user_owns_mod
from modstore_server.api.auth_deps import get_optional_user as _get_optional_user
from modstore_server.api.auth_deps import require_user as _require_user
from modstore_server.api.dto import (
    ConfigDTO,
    CreateModDTO,
    ExportFhdShellDTO,
    FocusPrimaryDTO,
    FrontendRegenerateDTO,
    HealthResponse,
    ManifestPutDTO,
    ModAiScaffoldDTO,
    ModFilePutDTO,
    SandboxDTO,
    SyncDTO,
    WorkflowEmployeeCatalogDTO,
)
from modstore_server.app_helpers import (
    _assert_path_inside_fhd_repo,
    _cfg,
    _fhd_repo_root,
    _lib,
    _load_state,
    _mod_dir,
    _save_state,
)
from modstore_server.auth_service import decode_access_token, get_user_by_id
from modstore_server.authoring import slim_openapi_paths
from modstore_server.constants import DEFAULT_XCAGI_BACKEND_URL
from modstore_server.employee_pack_export import build_employee_pack_zip_from_workflow
from modstore_server.file_safe import read_text_file, resolve_under_mod, write_text_file
from modstore_server.mod_ai_scaffold import (
    render_frontend_routes_js,
    render_generated_home_vue,
)
from modstore_server.mod_scaffold_runner import (
    analyze_mod_employee_readiness,
    patch_workflow_graph_employee_nodes,
    run_mod_suite_ai_scaffold_async,
)
from modstore_server.mod_snapshots import capture_manifest_snapshot
from modstore_server.models import (
    User,
    add_user_mod,
    get_session_factory,
    get_user_mod_ids,
    remove_user_mod,
)
from modstore_server.package_sandbox_audit import run_package_audit_async
from modstore_server.workflow_employee_scaffold import (
    WorkflowEmployeeScaffoldDTO,
    run_workflow_employee_scaffold,
    scaffold_auto_merge_default,
)

_TAGS = [
    {"name": "health", "description": "服务探活"},
    {
        "name": "config",
        "description": "库路径、XCAGI 根目录、后端 URL、导出 FHD 壳层 /api/mods JSON",
    },
    {"name": "mods", "description": "Mod 列表、详情、manifest、文件读写、导入导出"},
    {"name": "sync", "description": "与 XCAGI/mods 推送与拉回"},
    {"name": "debug", "description": "沙箱目录、primary 批量标记、XCAGI 状态代理"},
    {"name": "authoring", "description": "扩展面文档、蓝图路由静态扫描、宿主 OpenAPI 合并"},
    {"name": "payment", "description": "支付、订单与会员计划"},
    {"name": "workflow", "description": "工作流编排与执行"},
    {"name": "webhooks", "description": "业务 Webhook 投递与重放"},
    {"name": "refunds", "description": "退款申请与审核"},
    {"name": "catalog", "description": "公开目录与市场检索"},
    {
        "name": "catalog-mod-sync",
        "description": "公网机器令牌：库与 XCAGI/mods 推送/拉回（/v1/mod-sync）",
    },
]

api_router = APIRouter()


def _read_mod_json_file(mod_dir: Path, rel_path: str) -> Dict[str, Any]:
    rel = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel.startswith("/") or any(part == ".." for part in rel.split("/")):
        return {}
    p = mod_dir / rel
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _mod_shell_ui_row(mod_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    shell_from_manifest = frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
    ui_shell = _read_mod_json_file(mod_dir, str(config.get("ui_shell") or "config/ui_shell.json"))
    if not ui_shell:
        ui_shell = dict(shell_from_manifest)
    industry_card = _read_mod_json_file(
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
    industry_options: List[str] = []
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
    mod_dir: Path, manifest: Dict[str, Any], brief: str = ""
) -> Dict[str, Any]:
    mod_id = str(manifest.get("id") or mod_dir.name).strip() or mod_dir.name
    mod_name = str(manifest.get("name") or mod_id).strip() or mod_id
    desc = str(manifest.get("description") or "").strip()
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    blueprint = _read_mod_json_file(
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


@api_router.get("/api/health", tags=["health"], response_model=HealthResponse)
def health() -> HealthResponse:
    from modstore_server.deploy_context import health_payload

    return HealthResponse(ok=True, **health_payload())


@api_router.get("/api/config", tags=["config"])
def get_config():
    cfg = _cfg()
    lib = resolved_library(cfg)
    xc = resolved_xcagi(cfg)
    st = _load_state()
    return {
        "library_root": str(lib),
        "xcagi_root": str(xc) if xc else "",
        "library_exists": lib.is_dir(),
        "xcagi_ok": bool(xc and (xc / "mods").is_dir()),
        "saved_library_root": cfg.library_root,
        "saved_xcagi_root": cfg.xcagi_root,
        "saved_xcagi_backend_url": cfg.xcagi_backend_url,
        "xcagi_backend_url": resolved_xcagi_backend_url(cfg),
        "state": {
            "last_sandbox_mods_root": st.get("last_sandbox_mods_root") or "",
            "last_sandbox_mod_id": st.get("last_sandbox_mod_id") or "",
            "focus_mod_id": st.get("focus_mod_id") or "",
        },
    }


@api_router.post("/api/export/fhd-shell-mods", tags=["config"])
def api_export_fhd_shell_mods(body: ExportFhdShellDTO = Body(default_factory=ExportFhdShellDTO)):
    fhd = _fhd_repo_root()
    if not fhd.is_dir():
        raise HTTPException(500, "无法定位 FHD 仓库根目录（预期 MODstore 位于 FHD/MODstore）")
    raw = body.output_path or ""
    raw = raw.strip()
    if raw:
        target = Path(raw).expanduser().resolve()
    else:
        target = (fhd / "backend" / "shell" / "fhd_shell_mods.json").resolve()
    _assert_path_inside_fhd_repo(fhd, target)
    lib = _lib()
    n = write_fhd_shell_mods_json(lib, target)
    return {"ok": True, "path": str(target), "count": n}


@api_router.put("/api/config", tags=["config"])
def put_config(body: ConfigDTO):
    lr = (body.library_root or "").strip()
    xr = (body.xcagi_root or "").strip()
    url = (body.xcagi_backend_url or "").strip()
    cfg = RepoConfig(
        library_root=str(Path(lr).expanduser().resolve()) if lr else "",
        xcagi_root=str(Path(xr).expanduser().resolve()) if xr else "",
        xcagi_backend_url=url,
    )
    save_config(cfg)
    if cfg.library_root:
        Path(cfg.library_root).mkdir(parents=True, exist_ok=True)
    return get_config()


@api_router.get("/api/mods", tags=["mods"])
def api_list_mods(user: Optional[User] = Depends(_get_optional_user)):
    lib = _lib()
    if user is None:
        rows = []
    elif user.is_admin:
        rows = list_mods(lib)
    else:
        user_mod_ids = get_user_mod_ids(user.id)
        all_rows = list_mods(lib)
        rows = [r for r in all_rows if r.get("id") in user_mod_ids]
    return {"data": rows}


@api_router.get("/api/mods/shell-ui", tags=["mods"])
def api_mods_shell_ui(mod_id: str = ""):
    rows: List[Dict[str, Any]] = []
    for d in iter_mod_dirs(_lib()):
        data, err = read_manifest(d)
        if err or not data:
            continue
        rows.append(_mod_shell_ui_row(d, data))
    selected = None
    wanted = str(mod_id or "").strip()
    if wanted:
        selected = next((row for row in rows if row.get("id") == wanted), None)
    if selected is None:
        selected = next((row for row in rows if row.get("primary")), None)
    if selected is None and rows:
        selected = rows[0]
    industry_options: List[str] = []
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


@api_router.get("/api/mods/{mod_id}", tags=["mods"])
def api_get_mod(mod_id: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    data, err = read_manifest(d)
    if err or not data:
        raise HTTPException(400, err or "manifest 无效")
    ve = validate_manifest_dict(data)
    fn = folder_name_must_match_id(d, data)
    if fn:
        ve = list(ve) + [fn]
    files = list_mod_relative_files(d)
    sf = get_session_factory()
    with sf() as db:
        employee_readiness = analyze_mod_employee_readiness(db, user, d)
    return {
        "id": mod_id,
        "manifest": data,
        "validation_ok": len(ve) == 0,
        "warnings": ve,
        "files": files,
        "employee_readiness": employee_readiness,
    }


@api_router.get("/api/authoring/extension-surface", tags=["authoring"])
def api_authoring_extension_surface(merge_host: bool = False):
    bundled = load_bundled_extension_surface()
    result: Dict[str, Any] = {
        "ok": True,
        "bundled": bundled,
        "host_openapi": None,
        "host_openapi_error": None,
    }
    if merge_host:
        cfg = _cfg()
        base = resolved_xcagi_backend_url(cfg).rstrip("/")
        url = f"{base}/openapi.json"
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.get(url)
            if r.status_code >= 400:
                result["host_openapi_error"] = f"HTTP {r.status_code} from {url}"
            else:
                spec = r.json()
                routes = slim_openapi_paths(spec if isinstance(spec, dict) else {})
                result["host_openapi"] = {
                    "base_url": base,
                    "openapi_url": url,
                    "route_count": len(routes),
                    "routes": routes,
                }
        except httpx.RequestError as e:
            result["host_openapi_error"] = f"{type(e).__name__}: {e} ({url})"
        except json.JSONDecodeError as e:
            result["host_openapi_error"] = f"openapi.json 非 JSON: {e}"
    return result


@api_router.get("/api/mods/{mod_id}/blueprint-routes", tags=["authoring"])
def api_mod_blueprint_routes(mod_id: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    for rel in ("backend/blueprints.py", "blueprints.py"):
        p = d / rel
        if p.is_file():
            routes = scan_fastapi_router_routes(p)
            return {"ok": True, "file": rel, "routes": routes}
    return {
        "ok": True,
        "file": None,
        "routes": [],
        "hint": "未找到 backend/blueprints.py 或根目录 blueprints.py（FastAPI 路由扫描）",
    }


@api_router.get("/api/mods/{mod_id}/authoring-summary", tags=["authoring"])
def api_mod_authoring_summary(mod_id: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    data, err = read_manifest(d)
    if err or not data:
        raise HTTPException(400, err or "manifest 无效")
    ve = validate_manifest_dict(data)
    fn = folder_name_must_match_id(d, data)
    if fn:
        ve = list(ve) + [fn]
    bp_file: str | None = None
    bp_routes: List[Dict[str, Any]] = []
    for rel in ("backend/blueprints.py", "blueprints.py"):
        p = d / rel
        if p.is_file():
            bp_file = rel
            bp_routes = scan_fastapi_router_routes(p)
            break
    sf = get_session_factory()
    with sf() as db:
        employee_readiness = analyze_mod_employee_readiness(db, user, d)
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


@api_router.post("/api/mods/{mod_id}/workflow-employees/scaffold", tags=["authoring"])
def api_mod_workflow_employee_scaffold(
    mod_id: str, body: WorkflowEmployeeScaffoldDTO, user: User = Depends(_require_user)
):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    try:
        return run_workflow_employee_scaffold(
            d, body, allow_blueprint_merge=scaffold_auto_merge_default()
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@api_router.get("/api/mods/{mod_id}/export-employee-pack", tags=["authoring"])
def api_export_workflow_employee_pack(
    mod_id: str,
    workflow_index: int = 0,
    user: User = Depends(_require_user),
):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    data, err = read_manifest(d)
    if err or not data:
        raise HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or workflow_index < 0 or workflow_index >= len(rows):
        raise HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
    raw, build_err, pack_id = build_employee_pack_zip_from_workflow(
        mod_id,
        data,
        rows[workflow_index] if isinstance(rows[workflow_index], dict) else {},
        workflow_index=workflow_index,
        mod_dir=d,
    )
    if build_err or not raw or not pack_id:
        raise HTTPException(400, build_err or "生成员工包失败")
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pack_id}.xcemp"'},
    )


@api_router.post("/api/mods/{mod_id}/register-workflow-employee-catalog", tags=["authoring"])
async def api_register_workflow_employee_catalog(
    mod_id: str,
    body: WorkflowEmployeeCatalogDTO,
    user: User = Depends(_require_user),
):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    data, err = read_manifest(d)
    if err or not data:
        raise HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    idx = int(body.workflow_index)
    if not isinstance(rows, list) or idx < 0 or idx >= len(rows):
        raise HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
    entry = rows[idx] if isinstance(rows[idx], dict) else {}
    raw, build_err, pack_id = build_employee_pack_zip_from_workflow(
        mod_id,
        data,
        entry,
        workflow_index=idx,
        mod_dir=d,
    )
    if build_err or not raw or not pack_id:
        raise HTTPException(400, build_err or "生成员工包失败")

    audit = await run_package_audit_async(raw, {"artifact": "employee_pack"})
    if not audit.get("ok"):
        raise HTTPException(400, str(audit.get("error") or "包审核失败"))
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    if summary and summary.get("pass") is False:
        raise HTTPException(400, "五维审核未通过，禁止登记")

    import tempfile

    from modstore_server.catalog_store import append_package
    from modstore_server.models import CatalogItem

    manifest_zip, manifest_err, _pid = build_employee_pack_zip_from_workflow(
        mod_id,
        data,
        entry,
        workflow_index=idx,
        mod_dir=d,
    )
    if manifest_err or not manifest_zip:
        raise HTTPException(400, manifest_err or "生成员工包失败")
    from modstore_server.employee_pack_export import build_employee_pack_manifest_from_workflow

    manifest, manifest_build_err = build_employee_pack_manifest_from_workflow(
        mod_id,
        data,
        entry,
        workflow_index=idx,
    )
    if manifest_build_err or not manifest:
        raise HTTPException(400, manifest_build_err or "生成员工包 manifest 失败")

    rec: Dict[str, Any] = {
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
        tmp_path = Path(tmp.name)
    try:
        saved = append_package(rec, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    sf = get_session_factory()
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
        readiness = analyze_mod_employee_readiness(db, user, d)

    return {"ok": True, "package": saved, "audit": audit, "employee_readiness": readiness}


@api_router.post("/api/mods/{mod_id}/patch-workflow-employee-nodes", tags=["authoring"])
def api_patch_workflow_employee_nodes(mod_id: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    sf = get_session_factory()
    with sf() as db:
        out = patch_workflow_graph_employee_nodes(db, user, mod_dir=d, workflow_results=[])
        readiness = analyze_mod_employee_readiness(db, user, d)
    return {"ok": bool(out.get("ok")), "graph_patch": out, "employee_readiness": readiness}


@api_router.put("/api/mods/{mod_id}/manifest", tags=["mods"])
def api_put_manifest(mod_id: str, body: ManifestPutDTO, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    try:
        warnings = save_manifest_validated(d, body.manifest)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "warnings": warnings}


@api_router.get("/api/mods/{mod_id}/file", tags=["mods"])
def api_get_mod_file(mod_id: str, path: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    try:
        p = resolve_under_mod(d, path)
        text = read_text_file(p)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"path": path.replace("\\", "/").lstrip("/"), "content": text}


@api_router.put("/api/mods/{mod_id}/file", tags=["mods"])
def api_put_mod_file(mod_id: str, body: ModFilePutDTO, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    try:
        p = resolve_under_mod(d, body.path)
        write_text_file(p, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    manifest_warnings: List[str] = []
    if p.name == "manifest.json" and p.parent.resolve() == d.resolve():
        data, err = read_manifest(d)
        if data and not err:
            manifest_warnings = validate_manifest_dict(data)
            fn = folder_name_must_match_id(d, data)
            if fn:
                manifest_warnings = list(manifest_warnings) + [fn]
    return {"ok": True, "manifest_warnings": manifest_warnings}


@api_router.post("/api/mods/create", tags=["mods"])
def api_create_mod(body: CreateModDTO, user: User = Depends(_require_user)):
    mid = body.mod_id.strip().lower().replace(" ", "-")
    try:
        dest = create_mod(mid, body.display_name.strip(), _lib())
        apply_industry_to_mod_dir(dest, (body.industry_id or "通用").strip())
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    add_user_mod(user.id, mid)
    return {
        "ok": True,
        "path": str(dest),
        "id": mid,
        "industry_id": (body.industry_id or "通用").strip(),
    }


@api_router.post("/api/mods/ai-scaffold", tags=["mods"])
async def api_mod_ai_scaffold(body: ModAiScaffoldDTO, user: User = Depends(_require_user)):
    import logging

    logger = logging.getLogger(__name__)
    sf = get_session_factory()
    try:
        with sf() as db:
            res = await run_mod_suite_ai_scaffold_async(
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
        raise HTTPException(500, f"AI 脚手架异常：{exc}") from exc
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "AI 生成 Mod 失败")
    return res


@api_router.post("/api/mods/{mod_id}/frontend/regenerate", tags=["authoring"])
def api_mod_frontend_regenerate(
    mod_id: str,
    body: FrontendRegenerateDTO,
    user: User = Depends(_require_user),
):
    _assert_user_owns_mod(user, mod_id)
    mod_dir = _mod_dir(mod_id)
    manifest, err = read_manifest(mod_dir)
    if not manifest or err:
        raise HTTPException(400, err or "无法读取 manifest")
    try:
        snap = capture_manifest_snapshot(
            mod_dir, f"重新生成前端前 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception:  # noqa: BLE001
        snap = None
    spec = _frontend_spec_for_existing_mod(mod_dir, manifest, body.brief)
    mod_name = str(manifest.get("name") or mod_id)
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
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
    warnings = save_manifest_validated(mod_dir, manifest)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "frontend" / "views").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "frontend_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (mod_dir / "frontend" / "routes.js").write_text(
        render_frontend_routes_js(mod_id, mod_name, spec["entry_path"]), encoding="utf-8"
    )
    (mod_dir / "frontend" / "views" / "HomeView.vue").write_text(
        render_generated_home_vue(mod_id, mod_name, spec), encoding="utf-8"
    )
    return {
        "ok": True,
        "frontend_spec": spec,
        "entry_path": spec["entry_path"],
        "snapshot": snap,
        "manifest_warnings": warnings,
        "files": ["config/frontend_spec.json", "frontend/routes.js", "frontend/views/HomeView.vue"],
    }


@api_router.delete("/api/mods/{mod_id}", tags=["mods"])
def api_delete_mod(mod_id: str, user: User = Depends(_require_user)):
    mid = mod_id.strip()
    _assert_user_owns_mod(user, mid)
    try:
        remove_mod_by_manifest_id(_lib(), mid)
    except FileNotFoundError:
        raise HTTPException(404, "不存在") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    remove_user_mod(user.id, mid)
    return {"ok": True}


@api_router.post("/api/mods/import", tags=["mods"])
async def api_import_mod(
    file: UploadFile = File(...), replace: bool = True, user: User = Depends(_require_user)
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "请上传 .zip")
    raw = await file.read()
    max_bytes = int(os.environ.get("MODSTORE_CATALOG_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024)))
    if len(raw) > max_bytes:
        raise HTTPException(400, f"文件过大（>{max_bytes // 1024 // 1024}MB）")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        dest = import_zip(tmp_path, _lib(), replace=replace)
    except (ValueError, FileExistsError) as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)
    add_user_mod(user.id, dest.name)
    return {"ok": True, "id": dest.name, "path": str(dest)}


@api_router.get("/api/mods/{mod_id}/export", tags=["mods"])
def api_export_mod(mod_id: str, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, mod_id)
    d = _mod_dir(mod_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(d).as_posix())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{mod_id}.zip"'},
    )


@api_router.post("/api/sync/push", tags=["sync"])
def api_sync_push(body: SyncDTO, user: User = Depends(_require_user)):
    cfg = _cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(
            400, "未配置有效的 XCAGI 根目录（Mod 源码库页「路径与同步」或环境变量 XCAGI_ROOT）"
        )
    if not user.is_admin and body.mod_ids:
        for mod_id in body.mod_ids:
            _assert_user_owns_mod(user, mod_id)
    lib = _lib()
    try:
        done = deploy_to_xcagi(body.mod_ids, lib, xc, replace=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "deployed": done}


@api_router.post("/api/sync/pull", tags=["sync"])
def api_sync_pull(body: SyncDTO, user: User = Depends(_require_user)):
    cfg = _cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(400, "未配置有效的 XCAGI 根目录")
    lib = _lib()
    try:
        done = pull_from_xcagi(body.mod_ids, lib, xc, replace=True)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "pulled": done}


@api_router.post("/api/debug/sandbox", tags=["debug"])
def api_debug_sandbox(body: SandboxDTO, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, body.mod_id)
    mod_id = body.mod_id.strip()
    _mod_dir(mod_id)
    lib = _lib()
    src = (lib / mod_id).resolve()
    root = project_root()
    sand = root / "debug_sandbox"
    sand.mkdir(parents=True, exist_ok=True)
    session = uuid.uuid4().hex[:12]
    mods_root = (sand / session / "mods").resolve()
    mods_root.mkdir(parents=True, exist_ok=True)
    dst = mods_root / mod_id
    if dst.exists():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    try:
        if body.mode == "symlink":
            try:
                os.symlink(src, dst, target_is_directory=True)
            except OSError:
                shutil.copytree(src, dst)
        else:
            shutil.copytree(src, dst)
    except OSError as e:
        raise HTTPException(500, f"创建沙箱失败: {e}") from e
    path_str = str(mods_root)
    _save_state(
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


@api_router.post("/api/debug/focus-primary", tags=["debug"])
def api_debug_focus_primary(body: FocusPrimaryDTO, user: User = Depends(_require_user)):
    _assert_user_owns_mod(user, body.mod_id)
    target = body.mod_id.strip()
    _mod_dir(target)
    lib = _lib()
    updated: List[str] = []
    for d in iter_mod_dirs(lib):
        data, err = read_manifest(d)
        if err or not data:
            continue
        mid = (data.get("id") or d.name).strip()
        data["primary"] = mid == target
        try:
            write_manifest(d, data)
            updated.append(mid)
        except OSError as e:
            raise HTTPException(500, f"写入失败 {d.name}: {e}") from e
    _save_state({"focus_mod_id": target})
    return {"ok": True, "primary_mod_id": target, "updated_manifests": updated}


@api_router.get("/api/fhd/db-tokens/status", tags=["debug"])
def api_fhd_db_tokens_status():
    cfg = _cfg()
    base = resolved_xcagi_backend_url(cfg).rstrip("/")
    url = f"{base}/api/fhd/db-tokens/status"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except httpx.RequestError as e:
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "data": None,
        }
    try:
        payload = r.json()
    except json.JSONDecodeError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {
        "ok": ok,
        "status_code": r.status_code,
        "url": url,
        "data": payload if ok else None,
        "error": None if ok else (r.text or str(payload))[:500],
    }


@api_router.get("/api/xcagi/loading-status", tags=["debug"])
def api_xcagi_loading_status():
    cfg = _cfg()
    base = resolved_xcagi_backend_url(cfg)
    url = f"{base}/api/mods/loading-status"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except httpx.RequestError as e:
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "data": None,
        }
    try:
        payload = r.json()
    except json.JSONDecodeError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {
        "ok": ok,
        "status_code": r.status_code,
        "url": url,
        "data": payload,
    }


@api_router.get("/api/xcagi/installed-mods", tags=["sync"])
def api_xcagi_installed_mods():
    cfg = _cfg()
    xc = resolved_xcagi(cfg)
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
    rows: List[Dict[str, Any]] = []
    for d in iter_mod_dirs(mods_dir):
        data, err = read_manifest(d)
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


def _include_optional(app: FastAPI, module_path: str) -> None:
    try:
        mod = __import__(module_path, fromlist=["router"])
    except ImportError as exc:
        logging.getLogger(__name__).info("skip optional router %s: %s", module_path, exc)
        return
    except Exception as exc:
        logging.getLogger(__name__).exception("FATAL: router %s failed to load", module_path)
        raise
    router = getattr(mod, "router", None)
    if router is None:
        return
    app.include_router(router)
    hooks = getattr(mod, "workflow_hooks_router", None)
    if hooks is not None:
        app.include_router(hooks)


_OPTIONAL_MODULES = (
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.notification_api",
    "modstore_server.knowledge_vector_api",
    "modstore_server.knowledge_v2_api",
    "modstore_server.realtime_ws",
    "modstore_server.workflow_api",
    "modstore_server.script_workflow_api",
    "modstore_server.runtime_allowlist_api",
    "modstore_server.email_admin_api",
    "modstore_server.workbench_api",
    "modstore_server.employee_api",
    "modstore_server.analytics_api",
    "modstore_server.refund_api",
    "modstore_server.ops_api",
    "modstore_server.admin_ops_audit_api",
    "modstore_server.admin_employee_execution_api",
    "modstore_server.admin_duty_graph_api",
    "modstore_server.employee_change_request_api",
    "modstore_server.yuangon_onboard_admin_api",
    "modstore_server.webhook_api",
    "modstore_server.health_api",
    "modstore_server.openapi_connector_api",
    "modstore_server.customer_service_api",
    "modstore_server.developer_api",
    "modstore_server.developer_key_export_api",
    "modstore_server.webhook_subscription_api",
    "modstore_server.templates_api",
)


def _maybe_mount_dev_docs(app: FastAPI) -> None:
    docs_root = Path(__file__).resolve().parent.parent / "docs"
    if not docs_root.is_dir():
        return
    app.mount("/dev-docs", StaticFiles(directory=str(docs_root)), name="dev-docs")


def _maybe_mount_ui(app: FastAPI) -> None:
    root = Path(__file__).resolve().parent.parent
    dist = root / "web" / "dist"
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="ui-assets")

    index_file = dist / "index.html"

    @app.get("/")
    def ui_root():
        if index_file.is_file():
            return FileResponse(index_file)
        raise HTTPException(404)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if (
            full_path.startswith("api")
            or full_path.startswith("v1")
            or full_path.startswith("docs")
            or full_path.startswith("dev-docs")
            or full_path.startswith("redoc")
            or full_path.startswith("market")
            or full_path == "openapi.json"
        ):
            raise HTTPException(404)
        if index_file.is_file():
            return FileResponse(index_file)
        raise HTTPException(404)


def register_all_routes(app: FastAPI) -> None:
    from modstore_server.market_api import router as market_router
    from modstore_server.payment_api import router as payment_router

    app.include_router(market_router)
    app.include_router(payment_router)

    from modstore_server.catalog_api import router as catalog_public_router
    from modstore_server.mod_sync_catalog_api import router as mod_sync_catalog_router

    app.include_router(catalog_public_router)
    app.include_router(mod_sync_catalog_router)

    app.include_router(api_router)

    for _m in _OPTIONAL_MODULES:
        _include_optional(app, _m)

    _maybe_mount_dev_docs(app)
    _maybe_mount_ui(app)
