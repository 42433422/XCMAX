"""Installed Mod maintenance, update discovery and host bootstrap."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request

from .commands import LocalCommands
from .foundation import HostFoundation
from .schemas import ModStoreInstallResult, ModStoreSimpleResponse, ModStoreUpdatesResponse
from .updates import UpdateCoordinator


class LifecycleRoutes:
    """Installed Mod maintenance, update discovery and host bootstrap."""

    def __init__(
        self,
        *,
        commands: Callable[[], LocalCommands],
        updates: Callable[[], UpdateCoordinator],
        foundation: Callable[[], HostFoundation],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/reload-employees")
        async def mod_store_reload_employees(request: Request) -> ModStoreSimpleResponse:
            """显式刷新 employee_pack HTTP 路由与 Planner 工具注册表（装包后双保险）。"""
            return await commands().reload_employees(request)

        self.mod_store_reload_employees = mod_store_reload_employees

        @router.post("/uninstall", response_model=ModStoreSimpleResponse)
        async def mod_store_uninstall(request: Request) -> ModStoreSimpleResponse:
            return await commands().uninstall(request)

        self.mod_store_uninstall = mod_store_uninstall

        @router.post("/update", response_model=ModStoreInstallResult)
        async def mod_store_update(request: Request) -> ModStoreInstallResult:
            return await updates().apply(request)

        self.mod_store_update = mod_store_update

        @router.get("/validate", response_model=ModStoreSimpleResponse)
        async def mod_store_validate(mod_id: str = "") -> ModStoreSimpleResponse:
            return await commands().validate(mod_id)

        self.mod_store_validate = mod_store_validate

        @router.get("/updates", response_model=ModStoreUpdatesResponse)
        async def mod_store_updates(request: Request) -> ModStoreUpdatesResponse:
            return await updates().discover(request)

        self.mod_store_updates = mod_store_updates

        @router.post("/install-host-foundation", response_model=ModStoreSimpleResponse)
        async def mod_store_install_host_foundation(
            edition: str | None = Query(None, description="minimal | generic | full"),
        ) -> ModStoreSimpleResponse:
            """安装「宿主基础能力·预装员工」并 materialize 全部 bridge（非逐项 Mod 上架）。"""
            return await foundation().install_response(edition)

        self.mod_store_install_host_foundation = mod_store_install_host_foundation

        @router.post("/bootstrap-edition-pack", response_model=ModStoreSimpleResponse)
        async def mod_store_bootstrap_edition_pack(
            edition: str | None = Query(None, description="minimal | generic | full"),
        ) -> ModStoreSimpleResponse:
            """装齐当前 edition 所需 Mod：先复制安装包内置 mods/，再对缺失项尝试 Catalog。"""
            return await foundation().bootstrap(edition)

        self.mod_store_bootstrap_edition_pack = mod_store_bootstrap_edition_pack

        @router.post("/sync-modstore-library", response_model=ModStoreSimpleResponse)
        async def mod_store_sync_modstore_library(request: Request) -> ModStoreSimpleResponse:
            """使用修茈 PAT（须含 ``mod:sync``）从线上 ``/v1/mod-sync`` 拉 zip 并安装到本机 ``mods/``。"""
            return await commands().sync_modstore_library(request)

        self.mod_store_sync_modstore_library = mod_store_sync_modstore_library
