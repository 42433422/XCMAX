"""Local upload and catalog or customer-seed installation."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, File, Query, Request, UploadFile

from .commands import LocalCommands
from .packages import PackageInstaller
from .schemas import ModStoreInstallResult


class InstallRoutes:
    """Local upload and catalog or customer-seed installation."""

    def __init__(
        self,
        *,
        packages: Callable[[], PackageInstaller],
        commands: Callable[[], LocalCommands],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/upload", response_model=ModStoreInstallResult)
        async def mod_store_upload(
            file: UploadFile = File(..., description="Mod 包文件 (.xcemp 或 .zip)"),
            activate: bool = Query(True, description="安装后是否立即激活"),
        ) -> ModStoreInstallResult:
            """上传 Mod 包到本机并自动安装。

            进化状态闭环（2026-07-20）：
              - 接受 multipart/form-data 文件上传（最大 100MB）
              - 校验文件扩展名（.xcemp / .zip）
              - 落地到临时文件后调用 ``mod_manager.install_mod_package``
              - 返回安装结果（含 manifest 元数据）
            """
            return await packages().upload(file, activate)

        self.mod_store_upload = mod_store_upload

        @router.post("/install", response_model=ModStoreInstallResult)
        async def mod_store_install(request: Request) -> ModStoreInstallResult:
            return await commands().install(request)

        self.mod_store_install = mod_store_install

        @router.post("/install-industry-seed", response_model=ModStoreInstallResult)
        async def mod_store_install_industry_seed(request: Request) -> ModStoreInstallResult:
            """L2：从 industry-seeds 池安装所选行业中性 Mod；池缺失时 Catalog 兜底。"""
            return await commands().install_industry_seed(request)

        self.mod_store_install_industry_seed = mod_store_install_industry_seed

        @router.post("/install-customer-delivery-seed", response_model=ModStoreInstallResult)
        async def mod_store_install_customer_delivery_seed(
            request: Request,
        ) -> ModStoreInstallResult:
            """账号定制交付：从服务器下载客户种子包并导入本地业务数据。"""
            return await commands().install_customer_delivery_seed(request)

        self.mod_store_install_customer_delivery_seed = mod_store_install_customer_delivery_seed
