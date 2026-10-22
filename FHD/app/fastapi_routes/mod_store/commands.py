"""Commands for local Mod lifecycle, repository seeds and explicit library sync."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import CatalogInstall, InstalledMods, LibrarySync
from .schemas import ModStoreInstallResult, ModStoreSimpleResponse


class LocalCommands:
    def __init__(
        self,
        *,
        install: CatalogInstall,
        sync: LibrarySync,
        mods: Callable[[], InstalledMods],
        payload: Callable[[Request], Awaitable[dict[str, str]]],
        body_value: Callable[[Request, str], Awaitable[str]],
        split: Callable[[str], tuple[str, str]],
        text: Callable[[object], str],
        logger: logging.Logger,
    ) -> None:
        self._install = install
        self._sync = sync
        self._mods = mods
        self._payload = payload
        self._body_value = body_value
        self._split = split
        self._text = text
        self._logger = logger

    async def install(self, request: Request) -> ModStoreInstallResult:
        payload = await self._payload(request)
        pkg_id = self._text(payload.get("pkg_id") or payload.get("mod_id"))
        version = self._text(payload.get("version"))
        if not pkg_id:
            pkg_id, parsed_version = self._split(payload.get("package_file") or "")
            version = version or parsed_version
        activate = str(payload.get("activate") or "true").lower() not in {"0", "false", "no"}
        return await self._install(pkg_id, version, activate=activate)

    async def install_industry_seed(self, request: Request) -> ModStoreInstallResult:
        """L2：从 industry-seeds 池安装所选行业中性 Mod；池缺失时 Catalog 兜底。"""
        payload = await self._payload(request)
        raw = self._text(
            payload.get("industry_id") or payload.get("mod_id") or payload.get("industryId")
        )
        if not raw:
            raise HTTPException(status_code=400, detail="缺少 industry_id 或 mod_id")
        from app.mod_sdk.industry_seed import install_industry_seed_with_fallback

        data = await install_industry_seed_with_fallback(raw)
        return ModStoreInstallResult(
            success=bool(data.get("success")), message=str(data.get("message") or ""), data=data
        )

    async def install_customer_delivery_seed(self, request: Request) -> ModStoreInstallResult:
        """账号定制交付：从服务器下载客户种子包并导入本地业务数据。"""
        payload = await self._payload(request)
        mod_id = self._text(payload.get("mod_id") or payload.get("pkg_id"))
        industry_id = self._text(payload.get("industry_id") or payload.get("industryId"))
        if not mod_id:
            raise HTTPException(status_code=400, detail="缺少 mod_id")
        market_token = ""
        account_username = ""
        try:
            from app.fastapi_routes.market_account import resolve_valid_market_access_token
            from app.infrastructure.auth.dependencies import (
                resolve_session_user,
                session_id_from_request,
            )

            sid = session_id_from_request(request)
            if sid:
                market_token = await resolve_valid_market_access_token(sid) or ""
            user = resolve_session_user(request)
            if user is not None:
                account_username = (
                    str(user.get("username") or "").strip()
                    if isinstance(user, dict)
                    else str(getattr(user, "username", "") or "").strip()
                )
        except RECOVERABLE_ERRORS:
            self._logger.warning("customer delivery seed token resolve skipped", exc_info=True)
        from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package

        data = await install_customer_delivery_seed_package(
            request=request,
            mod_id=mod_id,
            industry_id=industry_id,
            market_token=market_token,
            account_username=account_username,
        )
        return ModStoreInstallResult(
            success=bool(data.get("success")), message=str(data.get("message") or ""), data=data
        )

    async def reload_employees(self, request: Request) -> ModStoreSimpleResponse:
        """显式刷新 employee_pack HTTP 路由与 Planner 工具注册表（装包后双保险）。"""
        payload = await self._payload(request)
        pack_id = self._text(payload.get("pack_id") or payload.get("pkg_id"))
        from app.mod_sdk.employee_runtime import refresh_employee_pack_runtime

        data = refresh_employee_pack_runtime(pack_id or None)
        return ModStoreSimpleResponse(
            success=True, message="员工包 Planner 注册表已刷新", data=data
        )

    async def uninstall(self, request: Request) -> ModStoreSimpleResponse:
        mod_id = await self._body_value(request, "mod_id")
        if not mod_id:
            raise HTTPException(status_code=400, detail="缺少 mod_id")
        ok, message = self._mods().uninstall_mod(mod_id, remove_files=True)
        return ModStoreSimpleResponse(success=bool(ok), message=message, data={"id": mod_id})

    async def validate(self, mod_id: str = "") -> ModStoreSimpleResponse:
        from app.infrastructure.mods.manifest import parse_manifest, validate_dependencies

        manager = self._mods()
        loaded = manager.get_mod(mod_id.strip()) if mod_id.strip() else None
        metadata = parse_manifest(loaded.mod_path) if loaded else None
        if metadata is None:
            return ModStoreSimpleResponse(
                success=False,
                message="未找到该 Mod 或 manifest.json 无法解析",
                data={"mod_id": mod_id},
            )
        satisfied = validate_dependencies(metadata, [m.id for m in manager.list_loaded_mods()])
        return ModStoreSimpleResponse(
            success=satisfied,
            message="清单校验通过" if satisfied else "依赖未满足",
            data={
                "mod_id": metadata.id,
                "version": metadata.version,
                "dependencies": metadata.dependencies,
                "dependencies_satisfied": satisfied,
            },
        )

    async def sync_modstore_library(self, request: Request) -> ModStoreSimpleResponse:
        """使用修茈 PAT（须含 ``mod:sync``）从线上 ``/v1/mod-sync`` 拉 zip 并安装到本机 ``mods/``。"""
        try:
            body = await request.json()
        except RECOVERABLE_ERRORS:
            raise HTTPException(status_code=400, detail="需要 JSON 请求体") from None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON 须为对象")
        base = (
            str(body.get("base_url") or body.get("baseUrl") or "").strip().rstrip("/")
            or "https://xiu-ci.com"
        )
        token = str(body.get("token") or "").strip()
        if not token:
            raise HTTPException(
                status_code=400, detail="缺少 token（修茈 Developer PAT，需含 mod:sync）"
            )
        sync_all = bool(body.get("all"))
        raw_ids = body.get("mod_ids")
        mod_ids: list[str] | None = None
        if isinstance(raw_ids, list):
            mod_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        elif isinstance(raw_ids, str) and raw_ids.strip():
            mod_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
        if not sync_all and (not mod_ids or len(mod_ids) == 0):
            raise HTTPException(
                status_code=400, detail="请指定 mod_ids（数组或逗号分隔字符串）或设置 all: true"
            )
        try:
            raw = await self._sync(
                base_url=base, token=token, mod_ids=mod_ids, sync_all_ok=sync_all
            )
            return ModStoreSimpleResponse(
                success=bool(raw.get("success")),
                message=str(raw.get("message") or ""),
                data=raw.get("data") if isinstance(raw.get("data"), dict) else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
