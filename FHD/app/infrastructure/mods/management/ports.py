"""Typed state and callback contracts at the Mod runtime boundaries."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any, Protocol

from fastapi import FastAPI

from ..manifest import ModMetadata

Payload = dict[str, Any]
ParseManifest = Callable[[str], ModMetadata | None]
ImportBackend = Callable[[str, str, str], ModuleType]
RecordFailure = Callable[[str, str, str], None]


class TrustedChild(Protocol):
    def __call__(self, parent: str, child_name: str, *, directory: bool) -> str | None: ...


class ExtractPackage(Protocol):
    def __call__(
        self, package_path: str, target_dir: str, verify_signature: bool = True
    ) -> tuple[str, Payload]: ...


class InstallPackage(Protocol):
    def __call__(
        self,
        package_path: str,
        verify_signature: bool = True,
        activate: bool = True,
        *,
        owner_scope: str = "",
    ) -> tuple[bool, str, ModMetadata | None]: ...


class InitHook(Protocol):
    def __call__(self, init_fn: Callable[..., object], *, mod_id: str | None = None) -> None: ...


class ValidateBundle(Protocol):
    def __call__(self, manifest: Payload, depth: int = 0) -> list[str]: ...


class RootState(Protocol):
    mods_root: str
    _explicit_mods_root: bool
    _ensure_attempts: int


class ScanState(Protocol):
    _scan_cache_fp: str
    _scan_cache_mods: list[ModMetadata]
    _scan_manifest_errors: list[dict[str, str]]


class PackageState(Protocol):
    mods_root: str
    _loaded_mods: list[str]
    _backend_entry_modules: dict[str, object]


class LifecycleState(PackageState, Protocol):
    _recent_load_failures: list[dict[str, str]]
    _blueprint_failures: list[dict[str, str]]


class MountRuntime(PackageState, Protocol):
    _http_routes_registered: set[str]
    _blueprint_failures: list[dict[str, str]]

    def resolve_mod_directory(self, mod_id: str) -> str | None: ...
    def record_blueprint_failure(self, mod_id: str, message: str) -> None: ...
    def load_mod(self, mod_id: str) -> bool: ...


class RegisterRoutes(Protocol):
    def __call__(
        self, app: FastAPI, mod_manager: MountRuntime | None, pack_id: str, *, force: bool = False
    ) -> bool: ...


class RegisterModRoutes(Protocol):
    def __call__(
        self, app: FastAPI, mod_manager: MountRuntime, mod_id: str, *, force: bool = False
    ) -> bool: ...


class EmployeeReadiness(Protocol):
    def __call__(
        self,
        mod_manager: MountRuntime,
        pack_id: str,
        *,
        registered_pack_ids: set[str],
        register_routes: RegisterRoutes,
    ) -> bool | None: ...


class EnsureApi(Protocol):
    def __call__(
        self, mod_id: str, session_id: str | None = None, *, requires_http: bool = True
    ) -> bool: ...
