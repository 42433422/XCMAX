"""Read-only catalog views combine local installation state and public remote metadata."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from fastapi import HTTPException

from app.application.mod_store.http_port_contracts import (
    JsonGet,
    MarketPage,
    PageMapper,
    Payload,
    RowFilter,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .projection import safe_text
from .schemas import (
    ModStoreCatalogPayload,
    ModStoreCatalogResponse,
    ModStoreDetailData,
    ModStoreDetailResponse,
    ModStoreListResponse,
    ModStoreMarketCatalogPayload,
    ModStoreMarketCatalogResponse,
)


class CatalogItem(Protocol):
    def model_dump(self) -> Payload: ...


@dataclass(frozen=True)
class CatalogPorts:
    items: Callable[[], Iterable[CatalogItem]]
    local_row: Callable[[Payload], Payload]
    local_rows: Callable[[], list[Payload]]
    installed: Callable[[], dict[str, Payload]]
    remote_row: Callable[[Payload, set[str]], Payload]
    remote_rows: Callable[[], Awaitable[list[Payload]]]
    foundation: Callable[[list[Payload], set[str]], None]
    combined: Callable[[], Awaitable[tuple[list[Payload], list[Payload]]]]
    filter: RowFilter
    map_page: PageMapper
    base_url: Callable[[], str]
    get_json: JsonGet
    market_page: MarketPage
    packages: Callable[[], AsyncIterator[Payload]]


class CatalogViews:
    def __init__(self, ports: CatalogPorts, logger: logging.Logger) -> None:
        self._ports = ports
        self._logger = logger

    def all_rows(self) -> list[dict[str, Any]]:
        try:
            items = self._ports.items()
            return [self._ports.local_row(x.model_dump()) for x in items]
        except RECOVERABLE_ERRORS as e:
            self._logger.warning("mod-store catalog: list_mod_items failed: %s", e)
            return []

    async def remote_rows(self) -> list[dict[str, Any]]:
        from app.mod_sdk.host_foundation import is_infrastructure_mod_hidden_from_store

        installed_ids = set(self._ports.installed())
        rows: list[dict[str, Any]] = []
        try:
            async for row in self._ports.packages():
                info = self._ports.remote_row(row, installed_ids)
                mid = str(info.get("id") or "").strip()
                if not mid:
                    continue
                if is_infrastructure_mod_hidden_from_store(mid) and (not row.get("public_listing")):
                    continue
                rows.append(info)
        except HTTPException as exc:
            self._logger.warning(
                "mod store remote catalog unavailable, using empty fallback: %s", exc
            )
        return rows

    async def map_market_catalog_page(
        self, data: dict[str, Any], *, collection_hint: str = ""
    ) -> tuple[list[dict[str, Any]], int]:
        from app.application.mod_store_catalog_app import (
            is_public_catalog_row,
            market_item_to_package_row,
        )

        installed_ids = set(self._ports.installed())
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
            info = self._ports.remote_row(row, installed_ids)
            hint = (
                collection_hint or str((row.get("commerce") or {}).get("collection") or "").strip()
            )
            if hint:
                info["store_collection"] = hint
            out.append(info)
        return (out, total)

    async def combined_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        from app.mod_sdk.host_foundation import is_infrastructure_mod_hidden_from_store

        installed_map = self._ports.installed()
        remote = await self._ports.remote_rows()
        seen = {str(r.get("id") or "") for r in remote}
        available = list(remote)
        for mid, local in installed_map.items():
            if mid and mid not in seen and (not is_infrastructure_mod_hidden_from_store(mid)):
                available.append(local)
        self._ports.foundation(available, set(installed_map.keys()))
        from app.mod_sdk.host_foundation import inject_aux_employee_pack_rows

        inject_aux_employee_pack_rows(available, set(installed_map.keys()))
        installed_visible = [
            r
            for r in installed_map.values()
            if not is_infrastructure_mod_hidden_from_store(str(r.get("id") or ""))
        ]
        return (available, installed_visible)

    async def catalog(self) -> ModStoreCatalogResponse:
        rows, installed = await self._ports.combined()
        return ModStoreCatalogResponse(
            data=ModStoreCatalogPayload(
                installed=installed, available=rows, indexed_count=len(rows)
            )
        )

    async def market_catalog(
        self,
        q: str | None = None,
        collection: str | None = None,
        artifact: str | None = None,
        material_category: str | None = None,
        license_scope: str | None = None,
        industry: str | None = None,
        security_level: str | None = None,
        limit: int = 80,
        offset: int = 0,
    ) -> ModStoreMarketCatalogResponse:
        """代理修茈 AI 市场 /api/market/catalog，合并本机安装态。"""
        data = await self._ports.market_page(
            q=q,
            collection=collection,
            artifact=artifact,
            material_category=material_category,
            license_scope=license_scope,
            industry=industry,
            security_level=security_level,
            limit=limit,
            offset=offset,
        )
        items, total = await self._ports.map_page(
            data, collection_hint=str(collection or "").strip()
        )
        return ModStoreMarketCatalogResponse(
            data=ModStoreMarketCatalogPayload(
                items=items, total=total, collection=str(collection or "").strip()
            )
        )

    async def search(
        self,
        q: str | None = None,
        author: str | None = None,
        installed: bool | None = None,
        limit: int = 50,
    ) -> ModStoreListResponse:
        rows, _installed = await self._ports.combined()
        out = self._ports.filter(rows, q=q, author=author, installed=installed)
        return ModStoreListResponse(data=out[:limit])

    async def popular(self, limit: int = 10) -> ModStoreListResponse:
        rows, _installed = await self._ports.combined()
        rows.sort(
            key=lambda r: r.get("total_downloads") or r.get("download_count") or 0, reverse=True
        )
        return ModStoreListResponse(data=rows[:limit])

    async def recent(self, limit: int = 10) -> ModStoreListResponse:
        rows, _installed = await self._ports.combined()
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return ModStoreListResponse(data=rows[:limit])

    async def details(self, mod_id: str) -> ModStoreDetailResponse:
        mid = (mod_id or "").strip()
        try:
            versions = await self._ports.get_json(f"/packages/by-id/{quote(mid, safe='')}/versions")
            rows = versions.get("versions") or []
            if isinstance(rows, list) and rows:
                latest = rows[0] if isinstance(rows[0], dict) else {"version": rows[0]}
                version = safe_text(latest.get("version")) or "1.0.0"
                detail = await self._ports.get_json(
                    f"/packages/{quote(mid, safe='')}/{quote(version, safe='')}"
                )
                return ModStoreDetailResponse(
                    data=ModStoreDetailData(
                        id=str(detail.get("id") or mid),
                        name=str(detail.get("name") or mid),
                        version=str(detail.get("version") or version),
                        author=str(detail.get("author") or detail.get("publisher") or "—"),
                        description=str(detail.get("description") or ""),
                        statistics=None,
                        ratings=[],
                        rating_count=0,
                        source="remote",
                        catalog_base_url=self._ports.base_url(),
                    )
                )
        except HTTPException as exc:
            self._logger.info("remote catalog detail fallback for %s: %s", mid, exc.detail)
        rows, _installed = await self._ports.combined()
        for r in rows:
            if str(r.get("id")) == mid:
                return ModStoreDetailResponse(
                    data=ModStoreDetailData(
                        id=str(r["id"]),
                        name=str(r["name"]),
                        version=str(r["version"]),
                        author=str(r["author"]),
                        description=str(r["description"]),
                        statistics=None,
                        ratings=[],
                        rating_count=0,
                        source=str(r.get("source") or "local"),
                        catalog_base_url=str(r.get("catalog_base_url") or self._ports.base_url()),
                    )
                )
        raise HTTPException(status_code=404, detail="未找到该 MOD")
