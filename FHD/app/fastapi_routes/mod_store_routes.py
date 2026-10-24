"""XCAGI MOD store HTTP contracts with explicit catalog, install and ownership adapters."""

from __future__ import annotations

import dataclasses as dataclasses
import hashlib as hashlib
import logging
import os as os
import tempfile as tempfile
from pathlib import Path as Path
from typing import Any
from typing import cast as cast
from urllib.parse import quote as quote

from fastapi import APIRouter, Request
from fastapi import File as File
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import UploadFile as UploadFile

from app.application.mod_store_catalog_app import (
    catalog_base_url,
    catalog_download_to,
    catalog_get_json,
    fetch_market_catalog_page,
    iter_catalog_packages,
    normalize_package_zip_path,
    sync_modstore_library_to_local,
)
from app.fastapi_routes.mod_store import foundation, projection, requests, workbench
from app.fastapi_routes.mod_store.catalog import CatalogPorts, CatalogViews
from app.fastapi_routes.mod_store.catalog_routes import CatalogRoutes
from app.fastapi_routes.mod_store.commands import LocalCommands
from app.fastapi_routes.mod_store.foundation import HostFoundation
from app.fastapi_routes.mod_store.install_routes import InstallRoutes
from app.fastapi_routes.mod_store.lifecycle_routes import LifecycleRoutes
from app.fastapi_routes.mod_store.packages import PackageInstaller
from app.fastapi_routes.mod_store.ports import EmployeePackWriter, InstalledMods, Payload
from app.fastapi_routes.mod_store.schemas import (
    AiModDeliveryStartBody as AiModDeliveryStartBody,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreCatalogPayload as ModStoreCatalogPayload,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreCatalogResponse as ModStoreCatalogResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreDependenciesResponse as ModStoreDependenciesResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreDetailData as ModStoreDetailData,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreDetailResponse as ModStoreDetailResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreInstallResult as ModStoreInstallResult,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreListResponse as ModStoreListResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreMarketCatalogPayload as ModStoreMarketCatalogPayload,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreMarketCatalogResponse as ModStoreMarketCatalogResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreNotImplementedResponse as ModStoreNotImplementedResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreRebuildResponse as ModStoreRebuildResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreSimpleResponse as ModStoreSimpleResponse,
)
from app.fastapi_routes.mod_store.schemas import (
    ModStoreUpdatesResponse as ModStoreUpdatesResponse,
)
from app.fastapi_routes.mod_store.updates import UpdateCoordinator
from app.fastapi_routes.mod_store.workbench import WorkbenchDelivery
from app.fastapi_routes.mod_store.workbench_routes import WorkbenchRoutes
from app.shell.mods_catalog import list_mod_items

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mod-store"])
_normalize_package_zip = normalize_package_zip_path


def _catalog() -> CatalogViews:
    return CatalogViews(
        CatalogPorts(
            items=list_mod_items,
            local_row=_item_to_mod_info,
            local_rows=_all_rows,
            installed=_installed_by_id,
            remote_row=_remote_to_mod_info,
            remote_rows=_remote_rows,
            foundation=_inject_host_foundation_row,
            combined=_combined_rows,
            filter=_filter_rows,
            map_page=_map_market_catalog_page,
            base_url=catalog_base_url,
            get_json=catalog_get_json,
            market_page=fetch_market_catalog_page,
            packages=iter_catalog_packages,
        ),
        logger,
    )


def _mod_manager() -> InstalledMods:
    from app.infrastructure.mods.mod_manager import get_mod_manager

    return get_mod_manager()


def _employee_registry() -> EmployeePackWriter:
    from app.infrastructure.mods.employee_registry import get_employee_registry

    return get_employee_registry()


def _artifact(path: str) -> str:
    from app.infrastructure.mods.artifact_package import peek_artifact

    return peek_artifact(path)


def _packages() -> PackageInstaller:
    return PackageInstaller(
        get_json=catalog_get_json,
        download=catalog_download_to,
        normalize_catalog=_normalize_package_zip,
        normalize_upload=normalize_package_zip_path,
        artifact=_artifact,
        mods=_mod_manager,
        employees=_employee_registry,
        foundation=_install_host_foundation_internal,
        logger=logger,
    )


def _updates() -> UpdateCoordinator:
    return UpdateCoordinator(
        installed=_installed_by_id,
        packages=iter_catalog_packages,
        install=_install_from_catalog,
        payload=_request_payload,
        split=_split_package_file,
        text=_safe_text,
    )


def _commands() -> LocalCommands:
    return LocalCommands(
        install=_install_from_catalog,
        sync=sync_modstore_library_to_local,
        mods=_mod_manager,
        payload=_request_payload,
        body_value=_body_value,
        split=_split_package_file,
        text=_safe_text,
        logger=logger,
    )


def _foundation() -> HostFoundation:
    return HostFoundation(
        _ensure_host_foundation_employee_on_disk,
        _can_materialize_host_foundation_without_employee_marker,
        _install_host_foundation_internal,
        logger,
    )


async def _market_proxy(
    method: str,
    path: str,
    *,
    json_body: Payload | None = None,
    authorization: str = "",
    timeout: float = 30.0,
    retries: int = 2,
) -> object:
    from app.fastapi_routes.market_account import _proxy_json

    return await _proxy_json(
        method,
        path,
        json_body=json_body,
        authorization=authorization,
        timeout=timeout,
        retries=retries,
    )


def _workbench() -> WorkbenchDelivery:
    return WorkbenchDelivery(_ai_mod_market_auth, _market_proxy, _install_from_catalog)


def _is_extension_row(d: dict[str, Any]) -> bool:
    return projection.is_extension_row(d)


def _item_to_mod_info(d: dict[str, Any]) -> dict[str, Any]:
    return projection.item_to_mod_info(d, base_url=catalog_base_url, is_extension=_is_extension_row)


def _all_rows() -> list[dict[str, Any]]:
    return _catalog().all_rows()


def _installed_by_id() -> dict[str, dict[str, Any]]:
    return {str(r.get("id") or ""): r for r in _all_rows() if r.get("is_installed")}


def _remote_to_mod_info(d: dict[str, Any], installed_ids: set[str]) -> dict[str, Any]:
    return projection.remote_to_mod_info(d, installed_ids, base_url=catalog_base_url)


async def _remote_rows() -> list[dict[str, Any]]:
    return await _catalog().remote_rows()


async def _map_market_catalog_page(
    data: dict[str, Any], *, collection_hint: str = ""
) -> tuple[list[dict[str, Any]], int]:
    return await _catalog().map_market_catalog_page(data, collection_hint=collection_hint)


def _inject_host_foundation_row(available: list[dict[str, Any]], installed_ids: set[str]) -> None:
    projection.inject_host_foundation_row(available, installed_ids)


async def _combined_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return await _catalog().combined_rows()


def _filter_rows(
    rows: list[dict[str, Any]],
    q: str | None = None,
    author: str | None = None,
    installed: bool | None = None,
) -> list[dict[str, Any]]:
    return projection.filter_rows(rows, q=q, author=author, installed=installed)


def _safe_text(value: Any) -> str:
    return projection.safe_text(value)


async def _body_value(request: Request, key: str, default: str = "") -> str:
    return await requests.body_value(request, key, default)


async def _request_payload(request: Request) -> dict[str, str]:
    return await requests.request_payload(request)


def _split_package_file(package_file: str) -> tuple[str, str]:
    return projection.split_package_file(package_file)


async def _ensure_host_foundation_employee_on_disk() -> tuple[bool, str]:
    """将内置 _employees/xcagi-host-foundation-employee 复制到用户 mods 目录（若尚未存在）。"""
    return await foundation.ensure_employee_on_disk()


def _can_materialize_host_foundation_without_employee_marker() -> bool:
    """Packaged builds can seed host bridges without the employee marker pack."""
    return foundation.can_materialize_without_marker()


async def _install_host_foundation_internal(edition: str | None) -> ModStoreInstallResult:
    return await _foundation().install(edition)


async def _install_from_catalog(
    pkg_id: str,
    version: str,
    activate: bool = True,
    *,
    authorization: str = "",
    download_path: str = "",
    expected_sha256: str = "",
    verify_signature: bool = True,
) -> ModStoreInstallResult:
    return await _packages().from_catalog(
        pkg_id,
        version,
        activate,
        authorization=authorization,
        download_path=download_path,
        expected_sha256=expected_sha256,
        verify_signature=verify_signature,
    )


def _ai_mod_market_auth(request: Request) -> str:
    return workbench.market_authorization(request)


from app.fastapi_routes.delivery_sync_routes import router as delivery_sync_router
from app.fastapi_routes.issue_runtime_routes import router as issue_runtime_router
from app.fastapi_routes.private_mod_delivery_progress_routes import (
    router as private_delivery_progress_router,
)
from app.fastapi_routes.private_mod_delivery_routes import router as private_delivery_router

router.include_router(private_delivery_router)
router.include_router(private_delivery_progress_router)
router.include_router(issue_runtime_router)
router.include_router(delivery_sync_router)


# HTTP owners retain the public endpoints and resolve service factories on each call.
_catalog_routes = CatalogRoutes(catalog=lambda: _catalog())
_install_routes = InstallRoutes(packages=lambda: _packages(), commands=lambda: _commands())
_workbench_routes = WorkbenchRoutes(delivery=lambda: _workbench())
_lifecycle_routes = LifecycleRoutes(
    commands=lambda: _commands(), updates=lambda: _updates(), foundation=lambda: _foundation()
)

router.include_router(_catalog_routes.router)
router.include_router(_install_routes.router)
router.include_router(_workbench_routes.router)
router.include_router(_lifecycle_routes.router)

mod_store_dependencies = _catalog_routes.mod_store_dependencies
mod_store_rate = _catalog_routes.mod_store_rate
mod_store_download = _catalog_routes.mod_store_download
mod_store_delete_package = _catalog_routes.mod_store_delete_package
mod_store_rebuild_index = _catalog_routes.mod_store_rebuild_index
mod_store_catalog = _catalog_routes.mod_store_catalog
mod_store_market_catalog = _catalog_routes.mod_store_market_catalog
mod_store_search = _catalog_routes.mod_store_search
mod_store_popular = _catalog_routes.mod_store_popular
mod_store_recent = _catalog_routes.mod_store_recent
mod_store_details = _catalog_routes.mod_store_details
mod_store_upload = _install_routes.mod_store_upload
mod_store_install = _install_routes.mod_store_install
mod_store_install_industry_seed = _install_routes.mod_store_install_industry_seed
mod_store_install_customer_delivery_seed = _install_routes.mod_store_install_customer_delivery_seed
ai_mod_delivery_start = _workbench_routes.ai_mod_delivery_start
ai_mod_delivery_status = _workbench_routes.ai_mod_delivery_status
ai_mod_delivery_install = _workbench_routes.ai_mod_delivery_install
mod_store_reload_employees = _lifecycle_routes.mod_store_reload_employees
mod_store_uninstall = _lifecycle_routes.mod_store_uninstall
mod_store_update = _lifecycle_routes.mod_store_update
mod_store_validate = _lifecycle_routes.mod_store_validate
mod_store_updates = _lifecycle_routes.mod_store_updates
mod_store_install_host_foundation = _lifecycle_routes.mod_store_install_host_foundation
mod_store_bootstrap_edition_pack = _lifecycle_routes.mod_store_bootstrap_edition_pack
mod_store_sync_modstore_library = _lifecycle_routes.mod_store_sync_modstore_library
