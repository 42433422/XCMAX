# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.routes_registry")


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
def api_delete_mod(mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)):
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
        _facade().os.environ.get("MODSTORE_CATALOG_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024))
    )
    if len(raw) > max_bytes:
        raise _facade().HTTPException(400, f"文件过大（>{max_bytes // 1024 // 1024}MB）")
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
def api_export_mod(mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)):
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
        _facade().logging.getLogger(__name__).info("skip optional router %s: %s", module_path, exc)
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
