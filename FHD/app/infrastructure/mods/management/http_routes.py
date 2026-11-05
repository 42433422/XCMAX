"""Register backend routes with an explicit runtime and declared route collaborators."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..artifact_constants import ARTIFACT_EMPLOYEE_PACK, normalize_artifact
from ..manifest import ModMetadata
from ..registry import ModRegistry
from .ports import ImportBackend, MountRuntime, ParseManifest, RegisterModRoutes, RegisterRoutes


@dataclass(frozen=True)
class HttpPorts:
    manager: Callable[[], MountRuntime]
    registry: Callable[[], ModRegistry]
    disabled: Callable[[], bool]
    parse: ParseManifest
    import_backend: ImportBackend
    resolve_metadata: Callable[[MountRuntime, str], ModMetadata | None]
    register_mod: RegisterModRoutes
    register_employee: RegisterRoutes
    load_employees: Callable[[FastAPI, MountRuntime | None], None]
    mount_primary: Callable[[MountRuntime | None], list[str]]
    registered_employees: set[str]
    short_error: Callable[[BaseException], str]
    logger: logging.Logger


class ModHttpRoutes:
    def __init__(self, ports: HttpPorts) -> None:
        self._ports = ports

    def register_employee(
        self, app: FastAPI, mod_manager: MountRuntime | None, pack_id: str, *, force: bool = False
    ) -> bool:
        """为单个 employee_pack 挂载 FastAPI 路由（安装后热加载）。"""
        pid = (pack_id or "").strip()
        if not pid or self._ports.disabled():
            return False
        if mod_manager is None:
            mod_manager = self._ports.manager()
        if not force and pid in self._ports.registered_employees:
            return True
        pack_path = os.path.join(mod_manager.mods_root, "_employees", pid)
        mf = os.path.join(pack_path, "manifest.json")
        if not os.path.isfile(mf):
            return False
        try:
            with open(mf, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if normalize_artifact(data) != ARTIFACT_EMPLOYEE_PACK:
            return False
        from app.mod_sdk.product_plane import employee_pack_allowed_in_runtime

        resolved_id = str(data.get("id") or pid).strip()
        if not employee_pack_allowed_in_runtime(resolved_id, data):
            self._ports.logger.debug(
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
            module = self._ports.import_backend(pack_path, resolved_id, entry)
            reg = getattr(module, "register_fastapi_routes", None)
            if callable(reg):
                reg(app, resolved_id)
                self._ports.registered_employees.add(resolved_id)
                self._ports.logger.info(
                    "FastAPI routes registered for employee_pack: %s", resolved_id
                )
                return True
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.error(
                "employee_pack route registration failed %s: %s", resolved_id, e, exc_info=True
            )
            mod_manager.record_blueprint_failure(resolved_id, str(e)[:500])
        return False

    def load_employees(self, app: FastAPI, mod_manager: MountRuntime | None = None) -> None:
        """为 ``mods/_employees/<pack_id>/`` 中带 ``backend.entry`` 的 employee_pack 挂载 FastAPI 路由。

        扫描目录不经过 ``scan_mods``（其忽略 ``_`` 前缀），故在此单独注册。
        """
        if mod_manager is None:
            mod_manager = self._ports.manager()
        if self._ports.disabled():
            return
        root = mod_manager.mods_root
        emp_root = os.path.join(root, "_employees")
        if not os.path.isdir(emp_root):
            return
        for name in sorted(os.listdir(emp_root)):
            pack_path = os.path.join(emp_root, name)
            if not os.path.isdir(pack_path):
                continue
            mf = os.path.join(pack_path, "manifest.json")
            if not os.path.isfile(mf):
                continue
            try:
                with open(mf, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if normalize_artifact(data) != ARTIFACT_EMPLOYEE_PACK:
                continue
            pack_id = str(data.get("id") or name).strip()
            if not pack_id:
                continue
            self._ports.register_employee(app, mod_manager, pack_id)

    def resolve_metadata(self, mod_manager: MountRuntime, mod_id: str) -> ModMetadata | None:
        """为 HTTP 挂载解析 Mod 元数据；Registry 未登记时从磁盘 manifest 补全。"""
        mid = (mod_id or "").strip()
        if not mid:
            return None
        registry = self._ports.registry()
        metadata = registry.get_mod_metadata(mid)
        needs_disk = (
            metadata is None
            or not (metadata.backend_entry or "").strip()
            or (not (metadata.mod_path or "").strip())
        )
        if needs_disk:
            mod_path = mod_manager.resolve_mod_directory(mid)
            if mod_path:
                parsed = self._ports.parse(mod_path)
                if parsed and (parsed.backend_entry or "").strip():
                    if metadata is None:
                        registry.register_mod(parsed)
                    metadata = parsed
        if not metadata or not (metadata.backend_entry or "").strip():
            return None
        return metadata

    def register_mod(
        self, app: FastAPI, mod_manager: MountRuntime, mod_id: str, *, force: bool = False
    ) -> bool:
        """为单个 Mod 挂载 /api/mod/{id}/*；已挂载则跳过（除非 force）。"""
        mid = (mod_id or "").strip()
        if not mid:
            return False
        if not force and mid in mod_manager._http_routes_registered:
            return True
        metadata = self._ports.resolve_metadata(mod_manager, mid)
        if not metadata:
            self._ports.logger.warning(
                "Mod %s has no backend_entry; skip HTTP route registration", mid
            )
            return False
        try:
            mod_fs_path = metadata.mod_path
            if not mod_fs_path:
                mod_manager.record_blueprint_failure(mid, "manifest 缺少 mod_path，无法注册路由")
                return False
            module = mod_manager._backend_entry_modules.get(mid)
            if module is None:
                module = self._ports.import_backend(mod_fs_path, mid, metadata.backend_entry)
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
                        self._ports.logger.info(
                            "Removed superseded host alias after loading Mod %s: %s",
                            mid,
                            removed_path,
                        )
                    self._ports.logger.info("FastAPI routes registered for mod: %s", mid)
                    registered = True
            if hasattr(module, "register_websocket_routes"):
                ws_register_fn = module.register_websocket_routes
                if callable(ws_register_fn):
                    ws_result = ws_register_fn(app)
                    if ws_result is False:
                        self._ports.logger.warning(
                            "WebSocket routes not registered for mod: %s", mid
                        )
                    else:
                        self._ports.logger.info("WebSocket routes registered for mod: %s", mid)
            if registered:
                mod_manager._http_routes_registered.add(mid)
                from app.infrastructure.mods.install_receipts import mark_runtime_loaded

                mark_runtime_loaded(mid, mods_root=mod_manager.mods_root, api_registered=True)
                return True
            self._ports.logger.info("Mod %s has no HTTP route registrar, skip", mid)
            return False
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.error("Failed to register routes for %s: %s", mid, e, exc_info=True)
            mod_manager.record_blueprint_failure(mid, self._ports.short_error(e))
            return False

    def load_all(self, app: FastAPI, mod_manager: MountRuntime | None = None) -> None:
        """加载 Mod 路由到 FastAPI 应用"""
        if mod_manager is None:
            mod_manager = self._ports.manager()
        self._ports.mount_primary(mod_manager)
        mod_manager._blueprint_failures = []
        registry = self._ports.registry()
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
            self._ports.register_mod(app, mod_manager, mod_id)
        self._ports.load_employees(app, mod_manager)
        from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

        ensure_spa_fallback_last(app)
