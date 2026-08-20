# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


class __ModManagerPart01MixinPart02Mixin:
    def _load_mod_backend(self, mod_id: str, mod_path: str, metadata: _facade().ModMetadata):
        backend_path = _facade()._trusted_child_path(mod_path, "backend", directory=True)
        if backend_path is None:
            _facade().logger.debug("No backend directory for mod: %s", mod_id)
            return
        if backend_path not in _facade().sys.path:
            _facade().sys.path.insert(0, backend_path)
        if metadata.backend_entry:
            try:
                module = _facade().import_mod_backend_py(mod_path, mod_id, metadata.backend_entry)
                self._backend_entry_modules[mod_id] = module
                if hasattr(module, metadata.backend_init):
                    init_fn = getattr(module, metadata.backend_init)
                    if callable(init_fn):
                        try:
                            _facade()._invoke_mod_init_hook(init_fn, mod_id=mod_id)
                        except TypeError as exc:
                            _facade().logger.warning(
                                "mod init hook %s for %s failed: %s",
                                metadata.backend_init,
                                mod_id,
                                exc,
                            )
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error(
                    "Failed to load backend entry for %s: %s", mod_id, e, exc_info=True
                )
                raise
        _facade()._register_mod_hooks(mod_id, metadata)

    def unload_mod(self, mod_id: str) -> bool:
        registry = _facade().get_mod_registry()
        instance = registry.get_mod_instance(mod_id)
        if instance and hasattr(instance, "cleanup"):
            try:
                instance.cleanup()
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error("Error cleaning up mod %s: %s", mod_id, e)
        registry.unregister_mod(mod_id)
        if mod_id in self._loaded_mods:
            self._loaded_mods.remove(mod_id)
        try:
            from app.infrastructure.mods.comms import get_mod_comms

            get_mod_comms().unregister_all(mod_id)
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("Mod comms cleanup failed for %s: %s", mod_id, e)
        _facade().logger.info("Mod unloaded: %s", mod_id)
        return True

    def install_mod_package(
        self, package_path: str, verify_signature: bool = True, activate: bool = True
    ) -> tuple[bool, str, _facade().ModMetadata | None]:
        """
        安装 MOD 包

        Args:
            package_path: .xcmod 文件路径
            verify_signature: 是否验证签名
            activate: 安装后是否立即激活

        Returns:
            (成功标志，消息，元数据)
        """
        try:
            self._refresh_mods_root_if_needed()
            _facade().os.makedirs(self.mods_root, exist_ok=True)
            self.invalidate_scan_cache()
            _facade().logger.info("Installing MOD package: %s", package_path)
            with _facade().tempfile.TemporaryDirectory() as temp_dir:
                try:
                    extract_path, manifest = _facade().ModPackage.extract_package(
                        package_path, temp_dir, verify_signature=verify_signature
                    )
                except _facade().ModSignatureError as e:
                    return (False, f"签名验证失败：{e}", None)
                except _facade().ModPackageError as e:
                    return (False, f"MOD 包无效：{e}", None)
                mod_id = manifest.get("id", "")
                if not mod_id:
                    return (False, "MOD 包缺少 id 字段", None)
                try:
                    from app.mod_sdk.product_skus import assert_mod_allowed_for_sku

                    assert_mod_allowed_for_sku(mod_id)
                except PermissionError as exc:
                    return (False, str(exc), None)
                target_path = _facade().os.path.join(self.mods_root, mod_id)
                if _facade().os.path.exists(target_path):
                    existing_metadata = _facade().parse_manifest(target_path)
                    existing_version = existing_metadata.version if existing_metadata else "unknown"
                    new_version = manifest.get("version", "unknown")
                    _facade().logger.info(
                        "MOD %s already exists (v%s), updating to v%s",
                        mod_id,
                        existing_version,
                        new_version,
                    )
                    _facade().shutil.rmtree(target_path)
                _facade().shutil.copytree(extract_path, target_path)
                _facade().logger.info("MOD installed to: %s", target_path)
                if activate:
                    if self.load_mod(mod_id):
                        metadata = _facade().parse_manifest(target_path)
                        return (True, f"MOD {mod_id} 安装成功", metadata)
                    else:
                        return (False, f"MOD {mod_id} 安装成功但加载失败", None)
                else:
                    metadata = _facade().parse_manifest(target_path)
                    return (True, f"MOD {mod_id} 安装成功（未激活）", metadata)
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.exception("MOD installation failed")
            return (False, f"安装失败：{e}", None)

    def uninstall_mod(self, mod_id: str, remove_files: bool = True) -> tuple[bool, str]:
        """
        卸载 MOD

        Args:
            mod_id: MOD ID
            remove_files: 是否删除文件

        Returns:
            (成功标志，消息)
        """
        try:
            registry = _facade().get_mod_registry()
            metadata = registry.get_mod_metadata(mod_id)
            if not metadata:
                from .employee_registry import get_employee_registry

                er = get_employee_registry(self.mods_root)
                emp_path = _facade().os.path.join(er._root(), mod_id)
                if _facade().os.path.isdir(emp_path):
                    ok, msg = er.uninstall_pack(mod_id, remove_files=remove_files)
                    return (ok, msg)
                return (False, f"MOD {mod_id} 未加载或不存在")
            _facade().logger.info("Uninstalling MOD: %s", mod_id)
            if mod_id in self._loaded_mods:
                self.unload_mod(mod_id)
            if remove_files:
                mod_path = _facade().os.path.join(self.mods_root, mod_id)
                if _facade().os.path.exists(mod_path):
                    _facade().shutil.rmtree(mod_path)
                    _facade().logger.info("MOD files removed: %s", mod_path)
            return (True, f"MOD {mod_id} 卸载成功")
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.exception("MOD uninstallation failed")
            return (False, f"卸载失败：{e}")
