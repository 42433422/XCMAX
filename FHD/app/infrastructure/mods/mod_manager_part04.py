# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


def register_employee_pack_routes(
    app, mod_manager: _facade().ModManager | None, pack_id: str, *, force: bool = False
) -> bool:
    """为单个 employee_pack 挂载 FastAPI 路由（安装后热加载）。"""
    pid = (pack_id or "").strip()
    if not pid or _facade().is_mods_disabled():
        return False
    if mod_manager is None:
        mod_manager = _facade().get_mod_manager()
    if not force and pid in _facade()._employee_pack_routes_registered:
        return True
    pack_path = _facade().os.path.join(mod_manager.mods_root, "_employees", pid)
    mf = _facade().os.path.join(pack_path, "manifest.json")
    if not _facade().os.path.isfile(mf):
        return False
    try:
        with open(mf, encoding="utf-8") as f:
            data = _facade().json.load(f)
    except (OSError, _facade().json.JSONDecodeError):
        return False
    if _facade().normalize_artifact(data) != _facade().ARTIFACT_EMPLOYEE_PACK:
        return False
    from app.mod_sdk.product_plane import employee_pack_allowed_in_runtime

    resolved_id = str(data.get("id") or pid).strip()
    if not employee_pack_allowed_in_runtime(resolved_id, data):
        _facade().logger.debug(
            "skip control-plane employee route in enterprise client: %s", resolved_id
        )
        return False
    backend = data.get("backend") or {}
    entry = str(backend.get("entry") or "").strip()
    if not entry:
        return False
    if not resolved_id:
        return False
    try:
        module = _facade().import_mod_backend_py(pack_path, resolved_id, entry)
        reg = getattr(module, "register_fastapi_routes", None)
        if callable(reg):
            reg(app, resolved_id)
            _facade()._employee_pack_routes_registered.add(resolved_id)
            _facade().logger.info("FastAPI routes registered for employee_pack: %s", resolved_id)
            return True
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error(
            "employee_pack route registration failed %s: %s", resolved_id, e, exc_info=True
        )
        mod_manager.record_blueprint_failure(resolved_id, str(e)[:500])
    return False


def load_employee_pack_routes(app, mod_manager: _facade().ModManager | None = None) -> None:
    """为 ``mods/_employees/<pack_id>/`` 中带 ``backend.entry`` 的 employee_pack 挂载 FastAPI 路由。

    扫描目录不经过 ``scan_mods``（其忽略 ``_`` 前缀），故在此单独注册。
    """
    if mod_manager is None:
        mod_manager = _facade().get_mod_manager()
    if _facade().is_mods_disabled():
        return
    root = mod_manager.mods_root
    emp_root = _facade().os.path.join(root, "_employees")
    if not _facade().os.path.isdir(emp_root):
        return
    for name in sorted(_facade().os.listdir(emp_root)):
        pack_path = _facade().os.path.join(emp_root, name)
        if not _facade().os.path.isdir(pack_path):
            continue
        mf = _facade().os.path.join(pack_path, "manifest.json")
        if not _facade().os.path.isfile(mf):
            continue
        try:
            with open(mf, encoding="utf-8") as f:
                data = _facade().json.load(f)
        except (OSError, _facade().json.JSONDecodeError):
            continue
        if _facade().normalize_artifact(data) != _facade().ARTIFACT_EMPLOYEE_PACK:
            continue
        pack_id = str(data.get("id") or name).strip()
        if not pack_id:
            continue
        _facade().register_employee_pack_routes(app, mod_manager, pack_id)


def _resolve_mod_metadata_for_http(
    mod_manager: _facade().ModManager, mod_id: str
) -> _facade().ModMetadata | None:
    """为 HTTP 挂载解析 Mod 元数据；Registry 未登记时从磁盘 manifest 补全。"""
    mid = (mod_id or "").strip()
    if not mid:
        return None
    registry = _facade().get_mod_registry()
    metadata = registry.get_mod_metadata(mid)
    needs_disk = (
        metadata is None
        or not (metadata.backend_entry or "").strip()
        or (not (metadata.mod_path or "").strip())
    )
    if needs_disk:
        mod_path = mod_manager.resolve_mod_directory(mid)
        if mod_path:
            parsed = _facade().parse_manifest(mod_path)
            if parsed and (parsed.backend_entry or "").strip():
                if metadata is None:
                    registry.register_mod(parsed)
                metadata = parsed
    if not metadata or not (metadata.backend_entry or "").strip():
        return None
    return metadata


def _register_single_mod_http_routes(
    app, mod_manager: _facade().ModManager, mod_id: str, *, force: bool = False
) -> bool:
    """为单个 Mod 挂载 /api/mod/{id}/*；已挂载则跳过（除非 force）。"""
    mid = (mod_id or "").strip()
    if not mid:
        return False
    if not force and mid in mod_manager._http_routes_registered:
        return True
    metadata = _facade()._resolve_mod_metadata_for_http(mod_manager, mid)
    if not metadata:
        _facade().logger.warning("Mod %s has no backend_entry; skip HTTP route registration", mid)
        return False
    try:
        mod_fs_path = metadata.mod_path
        if not mod_fs_path:
            mod_manager.record_blueprint_failure(mid, "manifest 缺少 mod_path，无法注册路由")
            return False
        module = mod_manager._backend_entry_modules.get(mid)
        if module is None:
            module = _facade().import_mod_backend_py(mod_fs_path, mid, metadata.backend_entry)
            mod_manager._backend_entry_modules[mid] = module
        registered = False
        if hasattr(module, "register_fastapi_routes"):
            register_fastapi_fn = module.register_fastapi_routes
            if callable(register_fastapi_fn):
                from app.legacy.routes.openapi_route_compat import (
                    iter_effective_routes,
                    remove_superseded_host_aliases,
                )

                app_router = getattr(app, "router", None)
                root_routes = getattr(app_router, "routes", []) or []
                routes_before = list(iter_effective_routes(root_routes))
                register_fastapi_fn(app, mid)
                for removed_path in remove_superseded_host_aliases(app, routes_before):
                    _facade().logger.info(
                        "Removed superseded host alias after loading Mod %s: %s",
                        mid,
                        removed_path,
                    )
                _facade().logger.info("FastAPI routes registered for mod: %s", mid)
                registered = True
        if hasattr(module, "register_websocket_routes"):
            ws_register_fn = module.register_websocket_routes
            if callable(ws_register_fn):
                ws_result = ws_register_fn(app)
                if ws_result is False:
                    _facade().logger.warning("WebSocket routes not registered for mod: %s", mid)
                else:
                    _facade().logger.info("WebSocket routes registered for mod: %s", mid)
        if registered:
            mod_manager._http_routes_registered.add(mid)
            return True
        _facade().logger.info("Mod %s has no HTTP route registrar, skip", mid)
        return False
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("Failed to register routes for %s: %s", mid, e, exc_info=True)
        mod_manager.record_blueprint_failure(mid, _facade()._short_exc_message(e))
        return False


def _restore_entitlements_from_session_id(session_id: str | None) -> None:
    """恢复企业 Mod 权益（委托给 dedicated 模块，保留旧调用方兼容）。"""
    _facade().restore_entitlements_from_session_id(session_id)


def _mod_allowed_for_api_load(mod_id: str, session_id: str | None = None) -> bool:
    mid = (mod_id or "").strip()
    if not mid:
        return False
    try:
        from app.enterprise.mod_entitlements import (
            enterprise_mod_filter_active,
            is_mod_visible_for_enterprise,
        )

        if not enterprise_mod_filter_active():
            return True
        if is_mod_visible_for_enterprise(mid):
            return True
    except _facade().RECOVERABLE_ERRORS:
        pass
    return False


def ensure_mod_api_ready(mod_id: str, session_id: str | None = None) -> bool:
    """
    访问 /api/mod/{mod_id}/... 前确保 Mod 已 load 且 HTTP 路由已挂载。
    修复企业版登录后 reload 未传 app、太阳鸟等客户 Mod 仅出现在列表但未 load 导致 404。
    """
    mid = (mod_id or "").strip()
    if not mid or _facade().is_mods_disabled():
        return False
    _facade()._restore_entitlements_from_session_id(session_id)
    if not _facade()._mod_allowed_for_api_load(mid, session_id):
        _facade().logger.warning("[ModManager] ensure_mod_api_ready: mod %s not allowed", mid)
        return False
    from app.infrastructure.mods.host_backed_compat import is_host_backed_compat_mod

    if is_host_backed_compat_mod(mid):
        # This route is registered by legacy_compat at host startup, so there
        # is no physical MOD directory to load or report as missing.
        _facade().clear_mod_missing_locally(mid)
        return True
    mm = _facade().get_mod_manager()
    employee_pack_ready = _facade().ensure_employee_pack_api_ready(
        mm,
        mid,
        registered_pack_ids=_facade()._employee_pack_routes_registered,
        register_routes=_facade().register_employee_pack_routes,
    )
    if employee_pack_ready is not None:
        return employee_pack_ready
    if mid not in mm._loaded_mods:
        if mm.resolve_mod_directory(mid) is None:
            recovered = False
            try:
                from app.mod_sdk.industry_seed import (
                    open_industry_seed_mod_ids,
                    seed_industry_mod,
                )

                if mid in set(open_industry_seed_mod_ids()):
                    seed_result = seed_industry_mod(mid)
                    recovered = bool(seed_result.get("success"))
                    if recovered:
                        _facade().clear_mod_missing_locally(mid)
                        _facade().logger.info(
                            "[ModManager] restored bundled industry seed before API mount: %s",
                            mid,
                        )
                    else:
                        _facade().logger.warning(
                            "[ModManager] bundled industry seed restore failed for %s: %s",
                            mid,
                            seed_result.get("message") or seed_result.get("status"),
                        )
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.warning(
                    "[ModManager] bundled industry seed restore error for %s: %s", mid, exc
                )
            if not recovered:
                _facade().mark_mod_missing_locally(mid)
                return False
        _facade().clear_mod_missing_locally(mid)
        if mid not in mm._loaded_mods:
            retry_at = _facade()._MOD_API_FAILURE_RETRY_AT.get(mid, 0.0)
            if retry_at > _facade().time.monotonic():
                _facade().logger.debug(
                    "[ModManager] ensure_mod_api_ready: load_mod(%s) retry delay active", mid
                )
                return False
            if not mm.load_mod(mid):
                _facade()._MOD_API_FAILURE_RETRY_AT[mid] = (
                    _facade().time.monotonic() + _facade()._MOD_API_FAILURE_BACKOFF_SECONDS
                )
                from app.runtime_integrity import record_runtime_issue

                record_runtime_issue(
                    f"industry_mod:{mid}",
                    f"Industry MOD failed to load: {mid}",
                    ttl_seconds=max(_facade()._MOD_API_FAILURE_BACKOFF_SECONDS * 2, 30.0),
                )
                _facade().logger.warning(
                    "[ModManager] ensure_mod_api_ready: load_mod(%s) failed", mid
                )
                return False
            _facade()._MOD_API_FAILURE_RETRY_AT.pop(mid, None)
            _facade().clear_mod_missing_locally(mid)
    if mid in mm._http_routes_registered:
        return True
    try:
        from app.fastapi_app import get_fastapi_app

        app = get_fastapi_app()
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("ensure_mod_api_ready: cannot get FastAPI app: %s", e)
        return False
    ok = _facade()._register_single_mod_http_routes(app, mm, mid)
    if ok:
        from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

        ensure_spa_fallback_last(app)
    return ok


def _entitled_client_mod_ids_for_api_mount(session_id: str | None = None) -> list[str]:
    """当前企业会话下允许挂载 API 的客户定制 Mod id（去重、排序）。"""
    try:
        from app.enterprise.mod_entitlements import (
            enterprise_mod_filter_active,
            get_cached_entitled_client_mod_ids,
            is_client_mod_id,
            is_mod_visible_for_enterprise,
        )
    except _facade().RECOVERABLE_ERRORS:
        return []
    if not enterprise_mod_filter_active():
        return []
    _facade()._restore_entitlements_from_session_id(session_id)
    candidates: set[str] = set()
    entitled = get_cached_entitled_client_mod_ids()
    if entitled:
        for mid in entitled:
            token = str(mid or "").strip()
            if token and is_client_mod_id(token) and is_mod_visible_for_enterprise(token):
                candidates.add(token)
    try:
        from app.mod_sdk.platform_shell import PROTECTED_CLIENT_MOD_IDS

        for mid in PROTECTED_CLIENT_MOD_IDS:
            token = str(mid or "").strip()
            if token and is_mod_visible_for_enterprise(token):
                candidates.add(token)
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        from app.mod_sdk.industry_seed import open_industry_seed_mod_ids

        open_seed_ids = set(open_industry_seed_mod_ids())
        mods_root = _facade().Path(_facade().get_mod_manager().mods_root)
        candidates = {
            mid for mid in candidates if mid not in open_seed_ids or (mods_root / mid).is_dir()
        }
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("filter unselected open industry seeds skipped", exc_info=True)
    return sorted(candidates)


def mount_entitled_client_mod_api_routes(app, session_id: str | None = None) -> list[str]:
    """
    登录后治根：为 entitlement 允许的客户 Mod 执行 load + /api/mod/{id}/* 挂载。

    与冷启动 ``load_all_mods`` 互补——避免无 session 时跳过、登录后仍 404。
    """
    if _facade().is_mods_disabled():
        return []
    mounted: list[str] = []
    for mid in _facade()._entitled_client_mod_ids_for_api_mount(session_id):
        if _facade().ensure_mod_api_ready(mid, session_id=session_id):
            mounted.append(mid)
    if mounted:
        from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

        ensure_spa_fallback_last(app)
        _facade().logger.info("[ModManager] mount_entitled_client_mod_api_routes: %s", mounted)
    return mounted


def mount_on_disk_primary_client_mods(mod_manager: _facade().ModManager | None = None) -> list[str]:
    """
    企业客户 Mod 不再因“磁盘存在”自动加载。

    通用安装包会在不同账号之间复用本机目录，客户定制包必须由会话 entitlement
    决定是否可见/可挂载；登录后通过 ensure_mod_api_ready 按需加载。

    因此本函数不再根据磁盘目录主动 load_mod，始终返回空列表，仅保留为兼容
    旧调用点的占位（load_mod_routes 等仍会调用它）。
    """
    return []


def load_mod_routes(app, mod_manager: _facade().ModManager | None = None) -> None:
    """加载 Mod 路由到 FastAPI 应用"""
    if mod_manager is None:
        mod_manager = _facade().get_mod_manager()
    _facade().mount_on_disk_primary_client_mods(mod_manager)
    mod_manager._blueprint_failures = []
    registry = _facade().get_mod_registry()
    routable: list[str] = []
    seen_ids: set[str] = set()
    for meta in registry.list_mods():
        mid = (meta.id or "").strip()
        if not mid or not (meta.backend_entry or "").strip():
            continue
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        routable.append(mid)
    ordered_ids: list[str] = []
    seen2: set[str] = set()
    for mid in mod_manager._loaded_mods:
        if mid in seen2 or mid not in seen_ids:
            continue
        ordered_ids.append(mid)
        seen2.add(mid)
    for mid in routable:
        if mid not in seen2:
            ordered_ids.append(mid)
            seen2.add(mid)
    for mod_id in ordered_ids:
        _facade()._register_single_mod_http_routes(app, mod_manager, mod_id)
    _facade().load_employee_pack_routes(app, mod_manager)
    from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

    ensure_spa_fallback_last(app)


def load_mod_blueprints(app, mod_manager: _facade().ModManager | None = None) -> None:
    """
    历史钩子名（兼容旧 Mod 文档/清单）。

    Mod 的 HTTP 面由 FastAPI ``load_mod_routes`` 注册；此函数为 no-op，避免重复挂载。
    """
    _facade().logger.info(
        "load_mod_blueprints: skipped (Mod routes use FastAPI load_mod_routes on main app)"
    )
