"""Discover and apply only the current workspace's authorized package update."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import HTTPException, Request

from .ports import CatalogInstall, Payload
from .schemas import ModStoreInstallResult, ModStoreUpdatesResponse


class UpdateCoordinator:
    def __init__(
        self,
        *,
        installed: Callable[[], dict[str, Payload]],
        packages: Callable[[], AsyncIterator[Payload]],
        install: CatalogInstall,
        payload: Callable[[Request], Awaitable[dict[str, str]]],
        split: Callable[[str], tuple[str, str]],
        text: Callable[[object], str],
    ) -> None:
        self._installed = installed
        self._packages = packages
        self._install = install
        self._payload = payload
        self._split = split
        self._text = text

    async def apply(self, request: Request) -> ModStoreInstallResult:
        from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
        from app.infrastructure.auth.dependencies import get_logged_in_user

        user = get_logged_in_user(request)
        owner = resolve_workspace_owner_id(request, user)
        if not owner:
            raise HTTPException(status_code=401, detail="无法确定当前工作空间")
        payload = await self._payload(request)
        parsed_id, parsed_version = self._split(payload.get("package_file") or "")
        pkg_id = self._text(payload.get("pkg_id") or payload.get("mod_id") or parsed_id)
        version = self._text(payload.get("version") or parsed_version)
        if parsed_id and parsed_id != pkg_id:
            raise HTTPException(status_code=400, detail="更新包与目标 MOD 不一致")
        discovery = await self.discover(request)
        update = next(
            (row for row in discovery.data["updates_available"] if row["mod_id"] == pkg_id), None
        )
        if not update or (version and update["new_version"] != version):
            raise HTTPException(status_code=409, detail="当前账号没有该版本更新，请刷新后重试")
        if update["source"] == "private_mod_sync":
            from app.application.mod_delivery_receipt_outbox import (
                retry_delivery_receipts_best_effort,
            )
            from app.application.private_mod_delivery_artifacts import (
                update_private_mod_from_library,
            )
            from app.fastapi_routes.private_mod_delivery_context import (
                _private_delivery_market_token,
            )

            token = await _private_delivery_market_token(request)
            result = await update_private_mod_from_library(
                pkg_id, token, expected_version=update["new_version"], owner_scope=owner
            )
            from app.application.delivery_entitlements import refresh_delivery_entitlements

            result["entitlements_refreshed"] = await refresh_delivery_entitlements(request, token)
            result["receipts"] = await retry_delivery_receipts_best_effort(request, token)
            return ModStoreInstallResult(success=True, message=result["message"], data=result)
        return await self._install(
            pkg_id, update["new_version"], activate=True, expected_sha256=update["package_sha256"]
        )

    async def discover(self, request: Request) -> ModStoreUpdatesResponse:
        from app.application.mod_update_discovery import available_updates
        from app.application.private_mod_delivery_artifacts import fetch_private_mod_library
        from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
        from app.fastapi_routes.private_mod_delivery_context import _private_delivery_market_token
        from app.infrastructure.auth.dependencies import get_logged_in_user
        from app.infrastructure.mods.install_receipts import read_verified_install

        user = get_logged_in_user(request)
        owner = resolve_workspace_owner_id(request, user)
        installed = self._installed()
        for mid in list(installed):
            receipt = read_verified_install(mid)
            if receipt and receipt.get("owner_scope") and (receipt["owner_scope"] != owner):
                installed.pop(mid)
        public_rows = []
        private_rows = []
        errors = {}
        try:
            public_rows = [row async for row in self._packages()]
        except HTTPException:
            errors["public_catalog"] = "公共更新源暂不可用"
        token = await _private_delivery_market_token(request)
        if token:
            try:
                private_rows = await fetch_private_mod_library(token)
            except HTTPException:
                errors["private_mod_sync"] = "账号私有更新源暂不可用"
        else:
            errors["private_mod_sync"] = "未登录市场账号，未检查私有更新"
        private_installed = {
            mid
            for mid in installed
            if (receipt := read_verified_install(mid)) and receipt.get("owner_scope")
        }
        public_rows = [
            row
            for row in public_rows
            if str(row.get("id") or row.get("pkg_id") or "") not in private_installed
        ]
        updates = available_updates(installed, public_rows, private_rows)
        return ModStoreUpdatesResponse(
            data={
                "updates_available": updates,
                "count": len(updates),
                "complete": not errors,
                "source_errors": errors,
            }
        )
