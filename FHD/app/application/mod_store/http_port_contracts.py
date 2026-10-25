"""Small typed boundaries for catalog, package installation and account transport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.fastapi_routes.mod_store.schemas import ModStoreInstallResult
from app.infrastructure.mods.manifest import ModMetadata

Payload = dict[str, Any]


class JsonGet(Protocol):
    async def __call__(self, path: str, *, headers: dict[str, str] | None = None) -> Payload: ...


class CatalogDownload(Protocol):
    async def __call__(
        self, path: str, dest: Path, *, headers: dict[str, str] | None = None
    ) -> object: ...


class RowFilter(Protocol):
    def __call__(
        self,
        rows: list[Payload],
        q: str | None = None,
        author: str | None = None,
        installed: bool | None = None,
    ) -> list[Payload]: ...


class PageMapper(Protocol):
    async def __call__(
        self, data: Payload, *, collection_hint: str = ""
    ) -> tuple[list[Payload], int]: ...


class MarketPage(Protocol):
    async def __call__(
        self,
        *,
        q: str | None = None,
        collection: str | None = None,
        artifact: str | None = None,
        material_category: str | None = None,
        license_scope: str | None = None,
        industry: str | None = None,
        security_level: str | None = None,
        limit: int = 80,
        offset: int = 0,
    ) -> Payload: ...


class ModPackageWriter(Protocol):
    def install_mod_package(
        self, package_path: str, verify_signature: bool = True, activate: bool = True
    ) -> tuple[bool, str, ModMetadata | None]: ...


class EmployeePackWriter(Protocol):
    def install_from_package(
        self, package_path: str, verify_signature: bool = True
    ) -> tuple[bool, str]: ...


class InstalledMods(ModPackageWriter, Protocol):
    def uninstall_mod(self, mod_id: str, remove_files: bool = True) -> tuple[bool, str]: ...
    def get_mod(self, mod_id: str) -> ModMetadata | None: ...
    def list_loaded_mods(self) -> list[ModMetadata]: ...


class CatalogInstall(Protocol):
    async def __call__(
        self,
        pkg_id: str,
        version: str,
        activate: bool = True,
        *,
        authorization: str = "",
        download_path: str = "",
        expected_sha256: str = "",
        verify_signature: bool = True,
    ) -> ModStoreInstallResult: ...


class FoundationInstall(Protocol):
    async def __call__(self, edition: str | None) -> ModStoreInstallResult: ...


class MarketProxy(Protocol):
    async def __call__(
        self,
        method: str,
        path: str,
        *,
        json_body: Payload | None = None,
        authorization: str = "",
        timeout: float = 30.0,
        retries: int = 2,
    ) -> object: ...


class LibrarySync(Protocol):
    async def __call__(
        self, *, base_url: str, token: str, mod_ids: list[str] | None, sync_all_ok: bool
    ) -> Payload: ...
