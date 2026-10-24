"""Load and unload one backend; apply dependency ordering across discovered Mods."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..artifact_constants import ARTIFACT_BUNDLE, normalize_artifact
from ..manifest import ModMetadata
from ..registry import ModRegistry
from .ports import (
    ImportBackend,
    InitHook,
    LifecycleState,
    ParseManifest,
    RecordFailure,
    TrustedChild,
)


@dataclass(frozen=True)
class LifecyclePorts:
    registry: Callable[[], ModRegistry]
    resolve: Callable[[str], str | None]
    roots: Callable[[], list[str]]
    scan: Callable[[], list[ModMetadata]]
    load: Callable[[str], bool]
    backend: Callable[[str, str, ModMetadata], None]
    parse: ParseManifest
    dependencies: Callable[[ModMetadata, list[str]], bool]
    record: RecordFailure
    child: TrustedChild
    import_backend: ImportBackend
    init: InitHook
    hooks: Callable[[str, ModMetadata], None]
    short_error: Callable[[BaseException], str]
    logger: logging.Logger


class ModLifecycle:
    def __init__(self, state: LifecycleState, ports: LifecyclePorts) -> None:
        self._state = state
        self._ports = ports

    def load(self, mod_id: str) -> bool:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id, is_retired_runtime_mod_id

        requested_mod_id = str(mod_id or "").strip()
        if is_retired_runtime_mod_id(requested_mod_id):
            mod_id = canonical_mod_id(requested_mod_id)
            self._ports.logger.info(
                "[ModManager] Redirect retired runtime mod %s -> %s",
                requested_mod_id,
                mod_id,
            )
        try:
            from app.mod_sdk.product_skus import assert_mod_allowed_for_sku

            assert_mod_allowed_for_sku(mod_id)
        except PermissionError as exc:
            self._ports.logger.warning("[ModManager] Mod blocked for SKU: %s — %s", mod_id, exc)
            self._ports.record(mod_id, "sku_policy", str(exc))
            return False
        registry = self._ports.registry()
        self._ports.logger.info("[ModManager] Attempting to load mod: %s", mod_id)
        if registry.get_mod_metadata(mod_id):
            self._ports.logger.info("[ModManager] Mod %s is already loaded", mod_id)
            if mod_id not in self._state._loaded_mods:
                self._ports.logger.warning(
                    "[ModManager] Mod %s in registry but missing from _loaded_mods; syncing list",
                    mod_id,
                )
                self._state._loaded_mods.append(mod_id)
            return True
        from app.infrastructure.mods.install_receipts import activate_pending_install

        if not activate_pending_install(mod_id, mods_root=self._state.mods_root):
            self._ports.record(mod_id, "restart_required", "Mod 更新需要重启后加载")
            return False
        mod_path = self._ports.resolve(mod_id)
        self._ports.logger.info("[ModManager] Mod path: %s", mod_path)
        if not mod_path:
            self._ports.record(mod_id, "fs", f"目录不存在（已搜索 mods 根: {self._ports.roots()}）")
            return False
        metadata = self._ports.parse(mod_path)
        if not metadata:
            self._ports.logger.error("[ModManager] Failed to parse manifest for mod: %s", mod_id)
            self._ports.record(mod_id, "manifest", "manifest.json 无效或缺少 id")
            return False
        self._ports.logger.info(
            "[ModManager] Mod metadata parsed: id=%s, name=%s, version=%s",
            metadata.id,
            metadata.name,
            metadata.version,
        )
        if normalize_artifact({"artifact": metadata.artifact}) == ARTIFACT_BUNDLE:
            if registry.get_mod_metadata(mod_id):
                return True
            if registry.register_mod(metadata):
                self._state._loaded_mods.append(mod_id)
                self._ports.logger.info(
                    "[ModManager] Registered bundle metadata only (no backend): %s", mod_id
                )
                return True
            self._ports.logger.warning("[ModManager] Bundle %s register_mod returned False", mod_id)
            return True
        deps = registry.list_mod_ids()
        self._ports.logger.info("[ModManager] Current loaded mods for dependency check: %s", deps)
        if not self._ports.dependencies(metadata, deps):
            self._ports.logger.warning(
                "[ModManager] Dependencies not satisfied for mod: %s", mod_id
            )
            self._ports.record(
                mod_id,
                "dependencies",
                "依赖未满足（需先加载所依赖的 mod，或检查 manifest dependencies）",
            )
            return False
        try:
            effective_id = (metadata.id or mod_id).strip()
            self._ports.backend(effective_id, mod_path, metadata)
            registry.register_mod(metadata)
            from app.infrastructure.mods.install_receipts import mark_runtime_loaded

            mark_runtime_loaded(effective_id, mods_root=self._state.mods_root)
            if effective_id not in self._state._loaded_mods:
                self._state._loaded_mods.append(effective_id)
            self._ports.logger.info(
                "[ModManager] Mod loaded successfully: %s%s",
                effective_id,
                f" (requested {mod_id})" if effective_id != mod_id else "",
            )
            return True
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.error(
                "[ModManager] Failed to load mod %s: %s", mod_id, e, exc_info=True
            )
            self._ports.record(mod_id, "backend", self._ports.short_error(e))
            return False

    def load_backend(self, mod_id: str, mod_path: str, metadata: ModMetadata):
        backend_path = self._ports.child(mod_path, "backend", directory=True)
        if backend_path is None:
            self._ports.logger.debug("No backend directory for mod: %s", mod_id)
            return
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        if metadata.backend_entry:
            try:
                module = self._ports.import_backend(mod_path, mod_id, metadata.backend_entry)
                self._state._backend_entry_modules[mod_id] = module
                if hasattr(module, metadata.backend_init):
                    init_fn = getattr(module, metadata.backend_init)
                    if callable(init_fn):
                        try:
                            self._ports.init(init_fn, mod_id=mod_id)
                        except TypeError as exc:
                            self._ports.logger.warning(
                                "mod init hook %s for %s failed: %s",
                                metadata.backend_init,
                                mod_id,
                                exc,
                            )
            except RECOVERABLE_ERRORS as e:
                self._ports.logger.error(
                    "Failed to load backend entry for %s: %s", mod_id, e, exc_info=True
                )
                raise
        self._ports.hooks(mod_id, metadata)

    def unload(self, mod_id: str) -> bool:
        registry = self._ports.registry()
        instance = registry.get_mod_instance(mod_id)
        if instance and hasattr(instance, "cleanup"):
            try:
                instance.cleanup()
            except RECOVERABLE_ERRORS as e:
                self._ports.logger.error("Error cleaning up mod %s: %s", mod_id, e)
        registry.unregister_mod(mod_id)
        if mod_id in self._state._loaded_mods:
            self._state._loaded_mods.remove(mod_id)
        try:
            from app.infrastructure.mods.comms import get_mod_comms

            get_mod_comms().unregister_all(mod_id)
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.warning("Mod comms cleanup failed for %s: %s", mod_id, e)
        self._ports.logger.info("Mod unloaded: %s", mod_id)
        return True

    def load_all(self) -> list[str]:
        self._state._recent_load_failures = []
        self._state._blueprint_failures = []
        mods = self._ports.scan()
        mods.sort(key=lambda m: (not m.primary, (m.id or "").lower()))
        self._ports.logger.info("[ModManager] load_all_mods: scanned %s mods", len(mods))
        loaded: list[str] = []
        for metadata in mods:
            try:
                from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

                if not is_mod_visible_for_enterprise(metadata.id):
                    self._ports.logger.info(
                        "[ModManager] Skipping mod %s (enterprise entitlement)", metadata.id
                    )
                    continue
            except RECOVERABLE_ERRORS:
                self._ports.record(metadata.id, "entitlement", "权益校验失败，未加载")
                continue
            self._ports.logger.info("[ModManager] Checking dependencies for mod: %s", metadata.id)
            if metadata.dependencies:
                deps_satisfied = self._ports.dependencies(metadata, loaded)
                if not deps_satisfied:
                    self._ports.logger.warning(
                        "[ModManager] Skipping mod %s due to unsatisfied dependencies", metadata.id
                    )
                    self._ports.record(
                        metadata.id,
                        "dependencies",
                        "load_all 阶段依赖未满足（可能需先加载其他 mod）",
                    )
                    continue
            if self._ports.load(metadata.id):
                loaded.append(metadata.id)
                self._ports.logger.info("[ModManager] Successfully loaded mod: %s", metadata.id)
            else:
                self._ports.logger.warning("[ModManager] Failed to load mod: %s", metadata.id)
        self._ports.logger.info("[ModManager] load_all_mods result: %s", loaded)
        return loaded
