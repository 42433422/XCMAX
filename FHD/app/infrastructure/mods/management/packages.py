"""Install and update packages through receipts; remove only a named local package."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..artifact_constants import ARTIFACT_BUNDLE, ARTIFACT_EMPLOYEE_PACK, normalize_artifact
from ..manifest import ModMetadata
from ..package import ModPackageError, ModSignatureError
from ..registry import ModRegistry
from .paths import is_package_directory_name
from .ports import (
    ExtractPackage,
    InstallPackage,
    PackageState,
    ParseManifest,
    Payload,
    ValidateBundle,
)

_PACKAGE_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (
    ModPackageError,
    ModSignatureError,
)


@dataclass(frozen=True)
class PackagePorts:
    registry: Callable[[], ModRegistry]
    refresh: Callable[[], None]
    invalidate: Callable[[], None]
    load: Callable[[str], bool]
    unload: Callable[[str], bool]
    install: InstallPackage
    extract: ExtractPackage
    parse: ParseManifest
    bundle_errors: ValidateBundle
    employee_errors: Callable[[Payload], list[str]]
    logger: logging.Logger


class ModPackages:
    def __init__(self, state: PackageState, ports: PackagePorts) -> None:
        self._state = state
        self._ports = ports

    def install(
        self,
        package_path: str,
        verify_signature: bool = True,
        activate: bool = True,
        *,
        owner_scope: str = "",
    ) -> tuple[bool, str, ModMetadata | None]:
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
            self._ports.refresh()
            os.makedirs(self._state.mods_root, exist_ok=True)
            self._ports.invalidate()
            self._ports.logger.info("Installing MOD package: %s", package_path)
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    extract_path, manifest = self._ports.extract(
                        package_path, temp_dir, verify_signature=verify_signature
                    )
                except ModSignatureError as e:
                    return (False, f"签名验证失败：{e}", None)
                except ModPackageError as e:
                    return (False, f"MOD 包无效：{e}", None)
                mod_id = manifest.get("id", "")
                if not mod_id:
                    return (False, "MOD 包缺少 id 字段", None)
                try:
                    from app.mod_sdk.product_skus import assert_mod_allowed_for_sku

                    assert_mod_allowed_for_sku(mod_id)
                except PermissionError as exc:
                    return (False, str(exc), None)
                from app.infrastructure.mods.install_receipts import install_extracted

                was_loaded = bool(
                    self._ports.registry().get_mod_metadata(mod_id)
                    or mod_id in self._state._loaded_mods
                    or mod_id in self._state._backend_entry_modules
                )
                restart_required = install_extracted(
                    mods_root=self._state.mods_root,
                    extracted_root=extract_path,
                    manifest=manifest,
                    package_path=package_path,
                    verify_signature=verify_signature,
                    was_loaded=was_loaded,
                    owner_scope=owner_scope,
                )
                self._ports.invalidate()
                target_path = os.path.join(self._state.mods_root, mod_id)
                if restart_required:
                    metadata = self._ports.parse(extract_path)
                    return (True, f"MOD {mod_id} 新版本已安装，重启后生效", metadata)
                if activate:
                    if self._ports.load(mod_id):
                        metadata = self._ports.parse(target_path)
                        return (True, f"MOD {mod_id} 安装成功", metadata)
                    else:
                        return (False, f"MOD {mod_id} 安装成功但加载失败", None)
                else:
                    metadata = self._ports.parse(target_path)
                    return (True, f"MOD {mod_id} 安装成功（未激活）", metadata)
        except _PACKAGE_ERRORS as e:
            self._ports.logger.exception("MOD installation failed")
            return (False, f"安装失败：{e}", None)

    def update(
        self, mod_id: str, package_path: str, verify_signature: bool = True
    ) -> tuple[bool, str, ModMetadata | None]:
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
            registry = self._ports.registry()
            if not registry.get_mod_metadata(mod_id):
                return (False, f"MOD {mod_id} 未安装，请先安装", None)
            with tempfile.TemporaryDirectory() as temporary:
                _, manifest = self._ports.extract(
                    package_path, temporary, verify_signature=verify_signature
                )
                if manifest.get("id") != mod_id:
                    return (False, "更新包身份与目标 MOD 不一致", None)
            from app.infrastructure.mods.install_receipts import read_verified_install

            current = read_verified_install(mod_id, mods_root=self._state.mods_root) or {}
            return self._ports.install(
                package_path,
                verify_signature=verify_signature,
                activate=True,
                owner_scope=str(current.get("owner_scope") or ""),
            )
        except _PACKAGE_ERRORS as exc:
            return (False, f"更新失败：{exc}", None)

    def uninstall(self, mod_id: str, remove_files: bool = True) -> tuple[bool, str]:
        """
        卸载 MOD

        Args:
            mod_id: MOD ID
            remove_files: 是否删除文件

        Returns:
            (成功标志，消息)
        """
        if not is_package_directory_name(mod_id):
            return (False, "非法 MOD id")
        try:
            registry = self._ports.registry()
            metadata = registry.get_mod_metadata(mod_id)
            if not metadata:
                from ..employee_registry import get_employee_registry

                er = get_employee_registry(self._state.mods_root)
                emp_path = os.path.join(er._root(), mod_id)
                if os.path.isdir(emp_path):
                    ok, msg = er.uninstall_pack(mod_id, remove_files=remove_files)
                    return (ok, msg)
                return (False, f"MOD {mod_id} 未加载或不存在")
            self._ports.logger.info("Uninstalling MOD: %s", mod_id)
            if mod_id in self._state._loaded_mods:
                self._ports.unload(mod_id)
            if remove_files:
                mod_path = os.path.join(self._state.mods_root, mod_id)
                if os.path.exists(mod_path):
                    shutil.rmtree(mod_path)
                    self._ports.logger.info("MOD files removed: %s", mod_path)
            return (True, f"MOD {mod_id} 卸载成功")
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.exception("MOD uninstallation failed")
            return (False, f"卸载失败：{e}")

    def validate(self, package_path: str) -> tuple[bool, str, Payload]:
        """
        验证 MOD 包

        Args:
            package_path: .xcmod 文件路径

        Returns:
            (有效标志，消息，详细信息)
        """
        try:
            if not os.path.isfile(package_path):
                return (False, "文件不存在", {})
            if not zipfile.is_zipfile(package_path):
                return (False, "不是有效的 ZIP 文件", {})
            with tempfile.TemporaryDirectory() as temp_dir:
                (extract_path, manifest) = self._ports.extract(
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
                art = normalize_artifact(manifest)
                if art == ARTIFACT_BUNDLE:
                    errors.extend(self._ports.bundle_errors(manifest, depth=0))
                elif art == ARTIFACT_EMPLOYEE_PACK:
                    errors.extend(self._ports.employee_errors(manifest))
                else:
                    backend_path = os.path.join(extract_path, "backend")
                    if os.path.isdir(backend_path):
                        backend_entry = manifest.get("backend", {}).get("entry", "")
                        if backend_entry:
                            entry_file = os.path.join(backend_path, f"{backend_entry}.py")
                            if not os.path.isfile(entry_file):
                                errors.append(f"后端入口文件不存在：{backend_entry}.py")
                    frontend_path = os.path.join(extract_path, "frontend")
                    if os.path.isdir(frontend_path):
                        frontend_routes = manifest.get("frontend", {}).get("routes", "")
                        if frontend_routes:
                            routes_file = os.path.join(frontend_path, f"{frontend_routes}.js")
                            if not os.path.isfile(routes_file):
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
        except ModPackageError as e:
            return (False, str(e), {})
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.exception("MOD validation failed")
            return (False, f"验证失败：{e}", {})
