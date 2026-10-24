"""Catalog discovery, package metadata and availability."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query

from .catalog import CatalogViews
from .schemas import (
    ModStoreCatalogResponse,
    ModStoreDependenciesResponse,
    ModStoreDetailResponse,
    ModStoreListResponse,
    ModStoreMarketCatalogResponse,
    ModStoreNotImplementedResponse,
    ModStoreRebuildResponse,
)


class CatalogRoutes:
    """Catalog discovery, package metadata and availability."""

    def __init__(
        self,
        *,
        catalog: Callable[[], CatalogViews],
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/dependencies", response_model=ModStoreDependenciesResponse)
        async def mod_store_dependencies() -> ModStoreDependenciesResponse:
            return ModStoreDependenciesResponse(
                data={
                    "mod_id": "",
                    "dependencies": [],
                    "satisfied": [],
                    "missing": [],
                    "can_install": True,
                }
            )

        self.mod_store_dependencies = mod_store_dependencies

        @router.post("/mod/{mod_id}/rate", response_model=ModStoreNotImplementedResponse)
        async def mod_store_rate(mod_id: str) -> ModStoreNotImplementedResponse:
            return ModStoreNotImplementedResponse(
                detail="评分 尚未在本后端实现；请将 Mod 包放入 XCAGI/mods 或通过 MODstore 工具链。"
            )

        self.mod_store_rate = mod_store_rate

        @router.get("/package/{package_file:path}/download")
        async def mod_store_download(package_file: str) -> None:
            raise HTTPException(status_code=404, detail="包下载未实现")

        self.mod_store_download = mod_store_download

        @router.delete(
            "/package/{package_file:path}", response_model=ModStoreNotImplementedResponse
        )
        async def mod_store_delete_package(package_file: str) -> ModStoreNotImplementedResponse:
            return ModStoreNotImplementedResponse(
                detail="删除包 尚未在本后端实现；请将 Mod 包放入 XCAGI/mods 或通过 MODstore 工具链。"
            )

        self.mod_store_delete_package = mod_store_delete_package

        @router.post("/index/rebuild", response_model=ModStoreRebuildResponse)
        async def mod_store_rebuild_index() -> ModStoreRebuildResponse:
            return ModStoreRebuildResponse(
                data={"indexed": 0, "failed": 0}, message="索引由磁盘 manifest 实时生成，无需重建。"
            )

        self.mod_store_rebuild_index = mod_store_rebuild_index

        @router.get("/catalog", response_model=ModStoreCatalogResponse)
        async def mod_store_catalog() -> ModStoreCatalogResponse:
            return await catalog().catalog()

        self.mod_store_catalog = mod_store_catalog

        @router.get("/market-catalog", response_model=ModStoreMarketCatalogResponse)
        async def mod_store_market_catalog(
            q: str | None = Query(None),
            collection: str | None = Query(None),
            artifact: str | None = Query(None),
            material_category: str | None = Query(None),
            license_scope: str | None = Query(None),
            industry: str | None = Query(None),
            security_level: str | None = Query(None),
            limit: int = Query(80, ge=1, le=200),
            offset: int = Query(0, ge=0),
        ) -> ModStoreMarketCatalogResponse:
            """代理修茈 AI 市场 /api/market/catalog，合并本机安装态。"""
            return await catalog().market_catalog(
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

        self.mod_store_market_catalog = mod_store_market_catalog

        @router.get("/search", response_model=ModStoreListResponse)
        async def mod_store_search(
            q: str | None = Query(None),
            author: str | None = Query(None),
            installed: bool | None = Query(None),
            limit: int = Query(50, ge=1, le=200),
        ) -> ModStoreListResponse:
            return await catalog().search(q=q, author=author, installed=installed, limit=limit)

        self.mod_store_search = mod_store_search

        @router.get("/popular", response_model=ModStoreListResponse)
        async def mod_store_popular(limit: int = Query(10, ge=1, le=200)) -> ModStoreListResponse:
            return await catalog().popular(limit)

        self.mod_store_popular = mod_store_popular

        @router.get("/recent", response_model=ModStoreListResponse)
        async def mod_store_recent(limit: int = Query(10, ge=1, le=200)) -> ModStoreListResponse:
            return await catalog().recent(limit)

        self.mod_store_recent = mod_store_recent

        @router.get("/mod/{mod_id}/details", response_model=ModStoreDetailResponse)
        async def mod_store_details(mod_id: str) -> ModStoreDetailResponse:
            return await catalog().details(mod_id)

        self.mod_store_details = mod_store_details
