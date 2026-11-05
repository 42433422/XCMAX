"""Public Mod runtime API; assemble explicit discovery, package and activation collaborators."""

from __future__ import annotations

import importlib as importlib
import json as json
import logging
import os
import shutil as shutil
import sys as sys
import tempfile as tempfile
import time
import zipfile as zipfile
from collections.abc import Callable
from pathlib import Path as Path
from types import ModuleType

from fastapi import FastAPI

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .artifact_constants import ARTIFACT_BUNDLE as ARTIFACT_BUNDLE
from .artifact_constants import ARTIFACT_EMPLOYEE_PACK as ARTIFACT_EMPLOYEE_PACK
from .artifact_constants import normalize_artifact as normalize_artifact
from .artifact_package import validate_bundle_manifest, validate_employee_pack_manifest
from .employee_pack_runtime import ensure_employee_pack_api_ready
from .enterprise_entitlement_restore import restore_entitlements_from_session_id
from .management import backend, paths
from .management.activation import ActivationPorts, ModActivation
from .management.activation import mod_allowed_for_api_load as _mod_allowed_for_api_load
from .management.discovery import DiscoveryPorts, ModDiscovery
from .management.http_routes import HttpPorts, ModHttpRoutes
from .management.lifecycle import LifecyclePorts, ModLifecycle
from .management.packages import ModPackages, PackagePorts
from .management.ports import MountRuntime, Payload
from .management.views import ModViews, ViewPorts, metadata_to_api_dict
from .manifest import ModMetadata, parse_manifest, validate_dependencies
from .missing_local_state import clear_mod_missing_locally, mark_mod_missing_locally
from .package import ModPackage
from .package import ModPackageError as ModPackageError
from .package import ModSignatureError as ModSignatureError
from .registry import get_mod_registry

logger = logging.getLogger(__name__)
_MOD_API_FAILURE_RETRY_AT: dict[str, float] = {}
_MOD_API_FAILURE_BACKOFF_SECONDS = 15.0
_employee_pack_routes_registered: set[str] = set()

is_mods_disabled = paths.is_mods_disabled
_trusted_child_path = paths.trusted_child_path
_short_exc_message = backend.short_exc_message


def _default_mods_root() -> str:
    return paths.default_mods_root(__file__, logger)


def _repo_layout_mods_candidates() -> list[str]:
    return paths.repo_layout_mods_candidates(__file__)


def _all_mods_roots(primary: str) -> list[str]:
    return paths.all_mods_roots(primary, _repo_layout_mods_candidates)


def _backend_path_for_mod(mod_path: str) -> str:
    return os.path.join(mod_path, "backend")


def _trusted_relative_file(parent: str, relative_path: str) -> str | None:
    return paths.trusted_relative_file(parent, relative_path, _trusted_child_path)


def import_mod_backend_py(mod_path: str, mod_id: str, stem: str) -> ModuleType:
    return backend.import_backend(
        mod_path, mod_id, stem, child=_trusted_child_path, relative_file=_trusted_relative_file
    )


def _register_mod_hooks(mod_id: str, metadata: ModMetadata) -> None:
    backend.register_hooks(mod_id, metadata, import_mod_backend_py, logger)


def _invoke_mod_init_hook(init_fn: Callable[..., object], *, mod_id: str | None = None) -> None:
    backend.invoke_init_hook(init_fn, mod_id=mod_id, logger=logger)


class ModManager:
    def __init__(self, mods_root: str | None = None) -> None:
        self._explicit_mods_root = mods_root is not None
        if mods_root is None:
            mods_root = _default_mods_root()
        else:
            if not os.fspath(mods_root).strip():
                raise ValueError("Explicit mods_root must not be empty")
            mods_root = os.path.abspath(mods_root)
            os.makedirs(mods_root, exist_ok=True)
        self.mods_root = mods_root
        self._loaded_mods: list[str] = []
        self._mod_import_cache: dict[str, object] = {}
        self._recent_load_failures: list[dict[str, str]] = []
        self._blueprint_failures: list[dict[str, str]] = []
        self._scan_manifest_errors: list[dict[str, str]] = []
        self._last_ensure_at: float = 0.0
        self._ensure_attempts: int = 0
        self._http_routes_registered: set[str] = set()
        self._scan_cache_fp: str = ""
        self._scan_cache_mods: list[ModMetadata] = []
        self._backend_entry_modules: dict[str, object] = {}

    def invalidate_scan_cache(self) -> None:
        self._scan_cache_fp = ""
        self._scan_cache_mods = []

    def _record_load_failure(self, mod_id: str, stage: str, message: str) -> None:
        self._recent_load_failures.append(
            {"mod_id": mod_id, "stage": stage, "message": message[:500]}
        )

    def record_blueprint_failure(self, mod_id: str, message: str) -> None:
        self._blueprint_failures.append({"mod_id": mod_id, "message": message[:500]})

    def get_recent_load_failures(self) -> list[dict[str, str]]:
        return list(self._recent_load_failures)

    def get_blueprint_failures(self) -> list[dict[str, str]]:
        return list(self._blueprint_failures)

    def get_scan_manifest_errors(self) -> list[dict[str, str]]:
        return list(self._scan_manifest_errors)

    def ensure_mods_loaded(self, app: FastAPI) -> None:
        """若注册表中尚无 Mod，但 mods 目录下存在合法 manifest，则再执行 load_all_mods + load_mod_routes。"""
        try:
            if is_mods_disabled():
                return
            self._refresh_mods_root_if_needed()
            if self.list_loaded_mods():
                return
            discovered = self.scan_mods()
            if not discovered:
                return
            now = time.monotonic()
            if self._last_ensure_at and now - self._last_ensure_at < 1.5:
                return
            if self._ensure_attempts >= 20:
                return
            self._last_ensure_at = now
            self._ensure_attempts += 1
            logger.warning(
                "[ModManager] 注册表无 Mod 但磁盘有 manifest，第 %s 次尝试加载：mods_root=%s，manifest 数=%s",
                self._ensure_attempts,
                self.mods_root,
                len(discovered),
            )
            self.load_all_mods()
            load_mod_routes(app, self)
        except RECOVERABLE_ERRORS as e:
            logger.exception(
                "[ModManager] ensure_mods_loaded failed (mods_root=%s): %s",
                getattr(self, "mods_root", None),
                e,
            )

    def all_mods_roots(self) -> list[str]:
        self._refresh_mods_root_if_needed()
        return _all_mods_roots(self.mods_root)

    def _refresh_mods_root_if_needed(self) -> None:
        paths.refresh_mods_root(self, _default_mods_root, logger)

    def _discovery(self) -> ModDiscovery:
        return ModDiscovery(
            self,
            DiscoveryPorts(
                roots=self.all_mods_roots,
                refresh=self._refresh_mods_root_if_needed,
                fingerprint=self._mods_scan_fingerprint,
                index=self._scan_mods_from_build_index,
                parse=parse_manifest,
                child=_trusted_child_path,
                logger=logger,
            ),
        )

    def _lifecycle(self) -> ModLifecycle:
        return ModLifecycle(
            self,
            LifecyclePorts(
                registry=get_mod_registry,
                resolve=self.resolve_mod_directory,
                roots=self.all_mods_roots,
                scan=self.scan_mods,
                load=self.load_mod,
                backend=self._load_mod_backend,
                parse=parse_manifest,
                dependencies=validate_dependencies,
                record=self._record_load_failure,
                child=_trusted_child_path,
                import_backend=import_mod_backend_py,
                init=_invoke_mod_init_hook,
                hooks=_register_mod_hooks,
                short_error=_short_exc_message,
                logger=logger,
            ),
        )

    def _packages(self) -> ModPackages:
        return ModPackages(
            self,
            PackagePorts(
                registry=get_mod_registry,
                refresh=self._refresh_mods_root_if_needed,
                invalidate=self.invalidate_scan_cache,
                load=self.load_mod,
                unload=self.unload_mod,
                install=self.install_mod_package,
                extract=ModPackage.extract_package,
                parse=parse_manifest,
                bundle_errors=validate_bundle_manifest,
                employee_errors=validate_employee_pack_manifest,
                logger=logger,
            ),
        )

    def _views(self) -> ModViews:
        return ModViews(
            ViewPorts(
                disabled=is_mods_disabled,
                refresh=self._refresh_mods_root_if_needed,
                root=lambda: self.mods_root,
                scan=self.scan_mods,
                project=self._metadata_to_api_dict,
                logger=logger,
            )
        )

    def _mods_scan_fingerprint(self) -> str:
        return self._discovery().fingerprint()

    def resolve_mod_directory(self, mod_id: str) -> str | None:
        return self._discovery().resolve_directory(mod_id)

    def _scan_mods_from_build_index(self, fp: str) -> list[ModMetadata] | None:
        return self._discovery().from_index(fp)

    def scan_mods(self, *, use_cache: bool = True) -> list[ModMetadata]:
        return self._discovery().scan(use_cache=use_cache)

    def load_mod(self, mod_id: str) -> bool:
        return self._lifecycle().load(mod_id)

    def _load_mod_backend(self, mod_id: str, mod_path: str, metadata: ModMetadata) -> None:
        self._lifecycle().load_backend(mod_id, mod_path, metadata)

    def unload_mod(self, mod_id: str) -> bool:
        return self._lifecycle().unload(mod_id)

    def load_all_mods(self) -> list[str]:
        return self._lifecycle().load_all()

    def install_mod_package(
        self,
        package_path: str,
        verify_signature: bool = True,
        activate: bool = True,
        *,
        owner_scope: str = "",
    ) -> tuple[bool, str, ModMetadata | None]:
        return self._packages().install(
            package_path, verify_signature, activate, owner_scope=owner_scope
        )

    def update_mod(
        self, mod_id: str, package_path: str, verify_signature: bool = True
    ) -> tuple[bool, str, ModMetadata | None]:
        return self._packages().update(mod_id, package_path, verify_signature)

    def uninstall_mod(self, mod_id: str, remove_files: bool = True) -> tuple[bool, str]:
        return self._packages().uninstall(mod_id, remove_files)

    def validate_mod_package(self, package_path: str) -> tuple[bool, str, Payload]:
        return self._packages().validate(package_path)

    def get_mod(self, mod_id: str) -> ModMetadata | None:
        return get_mod_registry().get_mod_metadata(mod_id)

    def list_loaded_mods(self) -> list[ModMetadata]:
        return get_mod_registry().list_mods()

    @staticmethod
    def _metadata_to_api_dict(m: ModMetadata) -> Payload:
        return metadata_to_api_dict(m)

    def list_mods(self) -> list[Payload]:
        return self.list_all_mods()

    def list_all_mods(self) -> list[Payload]:
        return self._views().list_all()

    def get_routes(self) -> list[dict[str, str]]:
        return self._views().routes()


_mod_manager: ModManager | None = None


def get_mod_manager() -> ModManager:
    global _mod_manager
    if _mod_manager is None:
        _mod_manager = ModManager()
    return _mod_manager


def _http_routes() -> ModHttpRoutes:
    return ModHttpRoutes(
        HttpPorts(
            manager=get_mod_manager,
            registry=get_mod_registry,
            disabled=is_mods_disabled,
            parse=parse_manifest,
            import_backend=import_mod_backend_py,
            resolve_metadata=_resolve_mod_metadata_for_http,
            register_mod=_register_single_mod_http_routes,
            register_employee=register_employee_pack_routes,
            load_employees=load_employee_pack_routes,
            mount_primary=mount_on_disk_primary_client_mods,
            registered_employees=_employee_pack_routes_registered,
            short_error=_short_exc_message,
            logger=logger,
        )
    )


def _activation() -> ModActivation:
    return ModActivation(
        ActivationPorts(
            manager=get_mod_manager,
            disabled=is_mods_disabled,
            restore=_restore_entitlements_from_session_id,
            allowed=_mod_allowed_for_api_load,
            employee_ready=ensure_employee_pack_api_ready,
            register_employee=register_employee_pack_routes,
            register_mod=_register_single_mod_http_routes,
            clear_missing=clear_mod_missing_locally,
            mark_missing=mark_mod_missing_locally,
            candidates=_entitled_client_mod_ids_for_api_mount,
            ensure=ensure_mod_api_ready,
            registered_employees=_employee_pack_routes_registered,
            retry_at=_MOD_API_FAILURE_RETRY_AT,
            retry_backoff=_MOD_API_FAILURE_BACKOFF_SECONDS,
            logger=logger,
        )
    )


def register_employee_pack_routes(
    app: FastAPI, mod_manager: MountRuntime | None, pack_id: str, *, force: bool = False
) -> bool:
    return _http_routes().register_employee(app, mod_manager, pack_id, force=force)


def load_employee_pack_routes(app: FastAPI, mod_manager: MountRuntime | None = None) -> None:
    _http_routes().load_employees(app, mod_manager)


def _resolve_mod_metadata_for_http(mod_manager: MountRuntime, mod_id: str) -> ModMetadata | None:
    return _http_routes().resolve_metadata(mod_manager, mod_id)


def _register_single_mod_http_routes(
    app: FastAPI, mod_manager: MountRuntime, mod_id: str, *, force: bool = False
) -> bool:
    return _http_routes().register_mod(app, mod_manager, mod_id, force=force)


def _restore_entitlements_from_session_id(session_id: str | None) -> None:
    restore_entitlements_from_session_id(session_id)


def ensure_mod_api_ready(
    mod_id: str, session_id: str | None = None, *, requires_http: bool = True
) -> bool:
    return _activation().ensure(mod_id, session_id, requires_http=requires_http)


def _entitled_client_mod_ids_for_api_mount(session_id: str | None = None) -> list[str]:
    return _activation().entitled_ids(session_id)


def mount_entitled_client_mod_api_routes(app: FastAPI, session_id: str | None = None) -> list[str]:
    return _activation().mount_entitled(app, session_id)


def mount_on_disk_primary_client_mods(mod_manager: MountRuntime | None = None) -> list[str]:
    """Retained entry point: only a session entitlement may activate a client Mod."""
    return []


def load_mod_routes(app: FastAPI, mod_manager: MountRuntime | None = None) -> None:
    _http_routes().load_all(app, mod_manager)


def load_mod_blueprints(app: FastAPI, mod_manager: MountRuntime | None = None) -> None:
    """The historical Flask hook remains a no-op; HTTP routes are owned by FastAPI."""
    logger.info("load_mod_blueprints: skipped (Mod routes use FastAPI load_mod_routes on main app)")
