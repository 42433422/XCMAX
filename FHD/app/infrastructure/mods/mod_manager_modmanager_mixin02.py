# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


class _ModManagerPart02Mixin:
    def update_mod(
        self, mod_id: str, package_path: str, verify_signature: bool = True
    ) -> tuple[bool, str, _facade().ModMetadata | None]:
        """
        更新 MOD

        Args:
            mod_id: MOD ID
            package_path: .xcmod 文件路径
            verify_signature: 是否验证签名

        Returns:
            (成功标志，消息，元数据)
        """
        try:
            registry = _facade().get_mod_registry()
            current_metadata = registry.get_mod_metadata(mod_id)
            if not current_metadata:
                return (False, f"MOD {mod_id} 未安装，请先安装", None)
            new_package = _facade().ModPackage(package_path)
            new_manifest = new_package.manifest
            current_version = current_metadata.version
            new_version = new_manifest.get("version", "unknown")
            _facade().logger.info(
                "Updating MOD %s: v%s -> v%s", mod_id, current_version, new_version
            )
            was_loaded = mod_id in self._loaded_mods
            if was_loaded:
                self.unload_mod(mod_id)
            mod_path = _facade().os.path.join(self.mods_root, mod_id)
            if _facade().os.path.exists(mod_path):
                _facade().shutil.rmtree(mod_path)
            with _facade().tempfile.TemporaryDirectory() as temp_dir:
                try:
                    (extract_path, _) = _facade().ModPackage.extract_package(
                        package_path, temp_dir, verify_signature=verify_signature
                    )
                    _facade().shutil.copytree(extract_path, mod_path)
                except _facade().RECOVERABLE_ERRORS as e:
                    _facade().logger.error("Failed to extract package: %s", e)
                    if was_loaded:
                        self.load_mod(mod_id)
                    return (False, f"更新失败：{e}", None)
            if was_loaded:
                if self.load_mod(mod_id):
                    metadata = _facade().parse_manifest(mod_path)
                    return (True, f"MOD {mod_id} 更新成功 (v{new_version})", metadata)
                else:
                    return (False, "MOD 更新成功但加载失败", None)
            else:
                metadata = _facade().parse_manifest(mod_path)
                return (True, f"MOD {mod_id} 更新成功 (v{new_version})", metadata)
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.exception("MOD update failed")
            return (False, f"更新失败：{e}", None)

    def validate_mod_package(self, package_path: str) -> tuple[bool, str, dict[str, _facade().Any]]:
        """
        验证 MOD 包

        Args:
            package_path: .xcmod 文件路径

        Returns:
            (有效标志，消息，详细信息)
        """
        try:
            if not _facade().os.path.isfile(package_path):
                return (False, "文件不存在", {})
            if not _facade().zipfile.is_zipfile(package_path):
                return (False, "不是有效的 ZIP 文件", {})
            with _facade().tempfile.TemporaryDirectory() as temp_dir:
                (extract_path, manifest) = _facade().ModPackage.extract_package(
                    package_path, temp_dir, verify_signature=True
                )
                mod_id = manifest.get("id", "")
                version = manifest.get("version", "")
                if not mod_id:
                    return (False, "缺少必填字段 'id'", {})
                errors: list[str] = []
                warnings: list[str] = []
                required_fields = ["id", "name", "version"]
                for field in required_fields:
                    if not manifest.get(field):
                        errors.append(f"缺少必填字段：{field}")
                art = _facade().normalize_artifact(manifest)
                if art == _facade().ARTIFACT_BUNDLE:
                    errors.extend(_facade().validate_bundle_manifest(manifest, depth=0))
                elif art == _facade().ARTIFACT_EMPLOYEE_PACK:
                    errors.extend(_facade().validate_employee_pack_manifest(manifest))
                else:
                    backend_path = _facade().os.path.join(extract_path, "backend")
                    if _facade().os.path.isdir(backend_path):
                        backend_entry = manifest.get("backend", {}).get("entry", "")
                        if backend_entry:
                            entry_file = _facade().os.path.join(backend_path, f"{backend_entry}.py")
                            if not _facade().os.path.isfile(entry_file):
                                errors.append(f"后端入口文件不存在：{backend_entry}.py")
                    frontend_path = _facade().os.path.join(extract_path, "frontend")
                    if _facade().os.path.isdir(frontend_path):
                        frontend_routes = manifest.get("frontend", {}).get("routes", "")
                        if frontend_routes:
                            routes_file = _facade().os.path.join(
                                frontend_path, f"{frontend_routes}.js"
                            )
                            if not _facade().os.path.isfile(routes_file):
                                errors.append(f"前端路由文件不存在：{frontend_routes}.js")
                is_valid = len(errors) == 0
                return (
                    is_valid,
                    "验证通过" if is_valid else "; ".join(errors),
                    {
                        "id": mod_id,
                        "name": manifest.get("name", ""),
                        "version": version,
                        "author": manifest.get("author", ""),
                        "artifact": art,
                        "errors": errors,
                        "warnings": warnings,
                    },
                )
        except _facade().ModPackageError as e:
            return (False, str(e), {})
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.exception("MOD validation failed")
            return (False, f"验证失败：{e}", {})

    def get_mod(self, mod_id: str) -> _facade().ModMetadata | None:
        registry = _facade().get_mod_registry()
        return registry.get_mod_metadata(mod_id)

    def list_loaded_mods(self) -> list[_facade().ModMetadata]:
        registry = _facade().get_mod_registry()
        return registry.list_mods()

    @staticmethod
    def _metadata_to_api_dict(m: _facade().ModMetadata) -> dict[str, _facade().Any]:
        """与前端 /api/mods/ 列表项、侧栏 manifest 展示字段对齐。"""
        art = _facade().normalize_artifact({"artifact": m.artifact})
        row: dict[str, _facade().Any] = {
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "author": m.author or "",
            "description": m.description or "",
            "primary": bool(m.primary),
            "artifact": art,
            "industry": dict(m.industry) if isinstance(m.industry, dict) else {},
            "ui_labels": dict(m.ui_labels) if isinstance(m.ui_labels, dict) else {},
            "ui_starter_pack": list(m.ui_starter_pack)
            if isinstance(m.ui_starter_pack, list)
            else [],
            "menu": list(m.frontend_menu) if m.frontend_menu else [],
            "frontend": {
                "pro_entry_path": str(getattr(m, "frontend_pro_entry_path", "") or "").strip()
            },
            "menu_overrides": list(m.frontend_menu_overrides) if m.frontend_menu_overrides else [],
            "workflow_employees": list(m.workflow_employees) if m.workflow_employees else [],
            "comms_exports": list(m.comms_exports) if m.comms_exports else [],
        }
        if art == _facade().ARTIFACT_BUNDLE:
            row["type"] = "bundle"
        return row

    def list_mods(self) -> list[dict[str, _facade().Any]]:
        """
        返回磁盘扫描 + 权益过滤后的 Mod 列表（与 list_all_mods 一致）。
        勿仅用 list_loaded_mods：企业版启动时未 entitlement 的客户 Mod
        不会进入 _loaded_mods，但登录后仍需按服务端 entitlement 在 /api/mods/ 中可见。
        """
        return self.list_all_mods()

    def list_all_mods(self) -> list[dict[str, _facade().Any]]:
        """
        始终返回磁盘扫描的全部 Mod 列表，不受已加载状态影响。
        供 GET /api/mods/?all=1 使用，返回所有可选的标准扩展包。
        """
        if _facade().is_mods_disabled():
            return []
        self._refresh_mods_root_if_needed()
        rows = [self._metadata_to_api_dict(x) for x in self.scan_mods()]
        try:
            from .employee_registry import get_employee_registry

            rows = rows + get_employee_registry(self.mods_root).list_for_mods_api()
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("employee registry merge skipped: %s", e)
        try:
            from app.enterprise.mod_entitlements import filter_mod_rows_for_enterprise

            rows = filter_mod_rows_for_enterprise(rows)
        except _facade().RECOVERABLE_ERRORS:
            pass
        return rows

    def get_routes(self) -> list[dict[str, str]]:
        """
        返回含 mod_id 的条目，供前端 registerModRoutes 匹配 Vite glob。
        manifest frontend.routes 非空即视为存在 frontend/routes.js（或约定路径）。
        """
        if _facade().is_mods_disabled():
            return []
        self._refresh_mods_root_if_needed()
        out: list[dict[str, str]] = []
        for m in self.scan_mods():
            try:
                from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

                if not is_mod_visible_for_enterprise(m.id):
                    continue
            except _facade().RECOVERABLE_ERRORS:
                pass
            rp = (m.frontend_routes or "").strip()
            if rp:
                out.append({"mod_id": m.id, "routes_path": rp})
        return out

    def load_all_mods(self) -> list[str]:
        self._recent_load_failures: list[dict[str, _facade().Any]] = []
        self._blueprint_failures: list[dict[str, _facade().Any]] = []
        mods = self.scan_mods()
        mods.sort(key=lambda m: (not m.primary, (m.id or "").lower()))
        _facade().logger.info("[ModManager] load_all_mods: scanned %s mods", len(mods))
        loaded: list[str] = []
        for metadata in mods:
            try:
                from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

                if not is_mod_visible_for_enterprise(metadata.id):
                    _facade().logger.info(
                        "[ModManager] Skipping mod %s (enterprise entitlement)", metadata.id
                    )
                    continue
            except _facade().RECOVERABLE_ERRORS:
                pass
            _facade().logger.info("[ModManager] Checking dependencies for mod: %s", metadata.id)
            if metadata.dependencies:
                deps_satisfied = _facade().validate_dependencies(metadata, loaded)
                if not deps_satisfied:
                    _facade().logger.warning(
                        "[ModManager] Skipping mod %s due to unsatisfied dependencies", metadata.id
                    )
                    self._record_load_failure(
                        metadata.id,
                        "dependencies",
                        "load_all 阶段依赖未满足（可能需先加载其他 mod）",
                    )
                    continue
            if self.load_mod(metadata.id):
                loaded.append(metadata.id)
                _facade().logger.info("[ModManager] Successfully loaded mod: %s", metadata.id)
            else:
                _facade().logger.warning("[ModManager] Failed to load mod: %s", metadata.id)
        _facade().logger.info("[ModManager] load_all_mods result: %s", loaded)
        return loaded
