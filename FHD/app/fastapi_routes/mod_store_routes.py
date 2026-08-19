"""XCAGI「MOD 商店」兼容 API：本机状态 + 修茈公网 Catalog 适配器。"""

from __future__ import annotations

import dataclasses as dataclasses
import logging
import os as os
import tempfile as tempfile
from pathlib import Path as Path
from typing import Any, Literal
from typing import cast as cast
from urllib.parse import quote as quote

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from fastapi import (
    File as File,
)
from fastapi import (
    Query as Query,
)
from fastapi import (
    UploadFile as UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field

from app.application.mod_store_catalog_app import (
    catalog_base_url,
    iter_catalog_packages,
    normalize_package_zip_path,
)
from app.application.mod_store_catalog_app import (
    catalog_download_to as catalog_download_to,
)
from app.application.mod_store_catalog_app import (
    catalog_get_json as catalog_get_json,
)
from app.application.mod_store_catalog_app import (
    fetch_market_catalog_page as fetch_market_catalog_page,
)
from app.application.mod_store_catalog_app import (
    sync_modstore_library_to_local as sync_modstore_library_to_local,
)
from app.shell.mods_catalog import list_mod_items
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mod-store"])


class ModStoreCatalogPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    installed: list[dict[str, Any]]
    available: list[dict[str, Any]]
    indexed_count: int


class ModStoreCatalogResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreCatalogPayload


class ModStoreListResponse(BaseModel):
    success: Literal[True] = True
    data: list[dict[str, Any]]


class ModStoreMarketCatalogPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[dict[str, Any]]
    total: int
    collection: str = ""


class ModStoreMarketCatalogResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreMarketCatalogPayload


class ModStoreDetailData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    version: str
    author: str
    description: str
    statistics: Any | None = None
    ratings: list[Any] = Field(default_factory=list)
    rating_count: int = 0
    source: str
    catalog_base_url: str


class ModStoreDetailResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreDetailData


class ModStoreInstallResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str
    data: dict[str, Any] | None = None


class ModStoreSimpleResponse(BaseModel):
    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None


class ModStoreUpdatesResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]


class ModStoreDependenciesResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]


class ModStoreRebuildResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]
    message: str | None = None


class ModStoreNotImplementedResponse(BaseModel):
    success: Literal[False] = False
    detail: str


def _is_extension_row(d: dict[str, Any]) -> bool:
    mid = str(d.get("id") or "").strip()
    if not mid or mid.lower() == "all":
        return False
    t = str(d.get("type") or "mod").strip().lower()
    if t in ("category", "template", "shell_seed"):
        return False
    return True


def _item_to_mod_info(d: dict[str, Any]) -> dict[str, Any]:
    mid = str(d.get("id") or "").strip()
    name = str(d.get("name") or mid or "未命名").strip() or mid
    ver = str(d.get("version") or "1.0.0").strip() or "1.0.0"
    author = str(d.get("author") or "—").strip() or "—"
    desc = str(d.get("description") or "").strip()
    installed = _is_extension_row(d)
    return {
        "id": mid,
        "name": name,
        "version": ver,
        "author": author,
        "description": desc,
        "package_file": None,
        "is_installed": installed,
        "download_count": 0,
        "total_downloads": 0,
        "avg_rating": 0.0,
        "rating_count": 0,
        "created_at": None,
        "dependencies": {},
        "source": "local",
        "catalog_base_url": catalog_base_url(),
    }


def _all_rows() -> list[dict[str, Any]]:
    try:
        items = list_mod_items()
        return [_item_to_mod_info(x.model_dump()) for x in items]
    except RECOVERABLE_ERRORS as e:
        logger.warning("mod-store catalog: list_mod_items failed: %s", e)
        return []


def _installed_by_id() -> dict[str, dict[str, Any]]:
    return {str(r.get("id") or ""): r for r in _all_rows() if r.get("is_installed")}


def _remote_to_mod_info(d: dict[str, Any], installed_ids: set[str]) -> dict[str, Any]:
    mid = str(d.get("id") or d.get("pkg_id") or "").strip()
    version = str(d.get("version") or "1.0.0").strip() or "1.0.0"
    name = str(d.get("name") or mid or "未命名").strip() or mid
    raw_commerce = d.get("commerce")
    commerce: dict[str, Any] = dict(raw_commerce) if isinstance(raw_commerce, dict) else {}
    download_url = str(d.get("download_url") or "").strip()
    from app.mod_sdk.host_foundation import catalog_store_collection

    row_out = {
        "id": mid,
        "pkg_id": mid,
        "name": name,
        "version": version,
        "author": str(
            (d or {}).get("author") or d.get("publisher") or commerce.get("seller") or "—"
        ).strip()
        or "—",
        "description": str(d.get("description") or "").strip(),
        "package_file": f"{mid}:{version}",
        "download_url": download_url,
        "is_installed": mid in installed_ids,
        "download_count": int(d.get("download_count") or d.get("total_downloads") or 0),
        "total_downloads": int(d.get("total_downloads") or d.get("download_count") or 0),
        "avg_rating": float(d.get("avg_rating") or 0.0),
        "rating_count": int(d.get("rating_count") or 0),
        "created_at": d.get("created_at") or d.get("updated_at"),
        "dependencies": d.get("dependencies") if isinstance(d.get("dependencies"), dict) else {},
        "artifact": d.get("artifact") or "mod",
        "sha256": d.get("sha256"),
        "commerce": commerce,
        "license": d.get("license"),
        "source": "remote",
        "catalog_base_url": catalog_base_url(),
        "store_collection": str(
            (d or {}).get("store_collection") or commerce.get("collection") or ""
        ).strip(),
        "public_listing": bool(d.get("public_listing")),
    }
    if not row_out["store_collection"]:
        row_out["store_collection"] = catalog_store_collection(row_out)
    return row_out


async def _remote_rows() -> list[dict[str, Any]]:

    from app.mod_sdk.host_foundation import is_infrastructure_mod_hidden_from_store

    installed_ids = set(_installed_by_id())
    rows: list[dict[str, Any]] = []
    try:
        async for row in iter_catalog_packages():
            info = _remote_to_mod_info(row, installed_ids)
            mid = str(info.get("id") or "").strip()
            if not mid:
                continue
            if is_infrastructure_mod_hidden_from_store(mid) and not row.get("public_listing"):
                continue
            rows.append(info)
    except HTTPException as exc:
        logger.warning("mod store remote catalog unavailable, using empty fallback: %s", exc)
    return rows


async def _map_market_catalog_page(
    data: dict[str, Any],
    *,
    collection_hint: str = "",
) -> tuple[list[dict[str, Any]], int]:
    from app.application.mod_store_catalog_app import (
        is_public_catalog_row,
        market_item_to_package_row,
    )

    installed_ids = set(_installed_by_id())
    items_raw = data.get("items") if isinstance(data.get("items"), list) else []
    try:
        total = int(data.get("total") or len(items_raw or []))
    except (TypeError, ValueError):
        total = len(items_raw or [])
    out: list[dict[str, Any]] = []
    for raw in items_raw or []:
        if not isinstance(raw, dict):
            continue
        row = market_item_to_package_row(raw)
        if not row or not is_public_catalog_row(row):
            continue
        info = _remote_to_mod_info(row, installed_ids)
        hint = collection_hint or str((row.get("commerce") or {}).get("collection") or "").strip()
        if hint:
            info["store_collection"] = hint
        out.append(info)
    return out, total


def _inject_host_foundation_row(available: list[dict[str, Any]], installed_ids: set[str]) -> None:
    from app.mod_sdk.host_foundation import (
        HOST_FOUNDATION_EMPLOYEE_PACK_ID,
        host_foundation_catalog_row,
        is_host_foundation_pack_installed,
        is_infrastructure_mod_hidden_from_store,
    )

    if any(str(r.get("id") or "") == HOST_FOUNDATION_EMPLOYEE_PACK_ID for r in available):
        return
    installed = (
        HOST_FOUNDATION_EMPLOYEE_PACK_ID in installed_ids or is_host_foundation_pack_installed()
    )
    available.insert(0, host_foundation_catalog_row(installed=installed))
    i = 0
    while i < len(available):
        mid = str(available[i].get("id") or "").strip()
        row = available[i]
        listed = bool(row.get("public_listing")) if isinstance(row, dict) else False
        if (
            mid != HOST_FOUNDATION_EMPLOYEE_PACK_ID
            and is_infrastructure_mod_hidden_from_store(mid)
            and not listed
        ):
            available.pop(i)
            continue
        i += 1


async def _combined_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.mod_sdk.host_foundation import is_infrastructure_mod_hidden_from_store

    installed_map = _installed_by_id()
    remote = await _remote_rows()
    seen = {str(r.get("id") or "") for r in remote}
    available = list(remote)
    for mid, local in installed_map.items():
        if mid and mid not in seen and not is_infrastructure_mod_hidden_from_store(mid):
            available.append(local)
    _inject_host_foundation_row(available, set(installed_map.keys()))
    from app.mod_sdk.host_foundation import inject_aux_employee_pack_rows

    inject_aux_employee_pack_rows(available, set(installed_map.keys()))
    installed_visible = [
        r
        for r in installed_map.values()
        if not is_infrastructure_mod_hidden_from_store(str(r.get("id") or ""))
    ]
    return available, installed_visible


def _filter_rows(
    rows: list[dict[str, Any]],
    q: str | None = None,
    author: str | None = None,
    installed: bool | None = None,
) -> list[dict[str, Any]]:
    out = rows
    if q and str(q).strip():
        k = str(q).strip().lower()
        out = [
            r
            for r in out
            if k in (r.get("name") or "").lower()
            or k in (r.get("id") or "").lower()
            or k in (r.get("description") or "").lower()
        ]
    if author and str(author).strip():
        a = str(author).strip().lower()
        out = [r for r in out if a in (r.get("author") or "").lower()]
    if installed is True:
        out = [r for r in out if r.get("is_installed")]
    elif installed is False:
        out = [r for r in out if not r.get("is_installed")]
    return out


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


async def _body_value(request: Request, key: str, default: str = "") -> str:
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            data = await request.json()
            if isinstance(data, dict):
                return _safe_text(data.get(key) or default)
            return default
        form = await request.form()
        return _safe_text(form.get(key) or default)
    except RECOVERABLE_ERRORS:
        return default


async def _request_payload(request: Request) -> dict[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            data = await request.json()
            return (
                {str(k): _safe_text(v) for k, v in data.items()} if isinstance(data, dict) else {}
            )
        form = await request.form()
        return {str(k): _safe_text(v) for k, v in form.items()}
    except RECOVERABLE_ERRORS:
        return {}


def _split_package_file(package_file: str) -> tuple[str, str]:
    raw = _safe_text(package_file)
    if ":" in raw:
        mid, version = raw.split(":", 1)
        return mid.strip(), version.strip()
    return raw, ""


_normalize_package_zip = normalize_package_zip_path




_delivery_routes = __import__("app.fastapi_routes.private_mod_delivery_routes", fromlist=["router"])
router.include_router(_delivery_routes.router)

from app.fastapi_routes import mod_store_route_handlers as _route_handlers

_ROUTE_HANDLER_EXPORTS = frozenset(['_can_materialize_host_foundation_without_employee_marker', '_ensure_host_foundation_employee_on_disk', '_install_from_catalog', '_install_host_foundation_internal', 'mod_store_bootstrap_edition_pack', 'mod_store_catalog', 'mod_store_delete_package', 'mod_store_dependencies', 'mod_store_details', 'mod_store_download', 'mod_store_install', 'mod_store_install_customer_delivery_seed', 'mod_store_install_host_foundation', 'mod_store_install_industry_seed', 'mod_store_market_catalog', 'mod_store_popular', 'mod_store_rate', 'mod_store_rebuild_index', 'mod_store_recent', 'mod_store_reload_employees', 'mod_store_search', 'mod_store_sync_modstore_library', 'mod_store_uninstall', 'mod_store_update', 'mod_store_updates', 'mod_store_upload', 'mod_store_validate'])


def __getattr__(name: str):
    if name in _ROUTE_HANDLER_EXPORTS:
        return getattr(_route_handlers, name)
    raise AttributeError(name)
