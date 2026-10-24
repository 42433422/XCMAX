"""Authorize on-demand activation and coordinate bounded retries and API mounts."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import EmployeeReadiness, EnsureApi, MountRuntime, RegisterModRoutes, RegisterRoutes


@dataclass(frozen=True)
class ActivationPorts:
    manager: Callable[[], MountRuntime]
    disabled: Callable[[], bool]
    restore: Callable[[str | None], None]
    allowed: Callable[[str, str | None], bool]
    employee_ready: EmployeeReadiness
    register_employee: RegisterRoutes
    register_mod: RegisterModRoutes
    clear_missing: Callable[[str], None]
    mark_missing: Callable[[str], None]
    candidates: Callable[[str | None], list[str]]
    ensure: EnsureApi
    registered_employees: set[str]
    retry_at: dict[str, float]
    retry_backoff: float
    logger: logging.Logger


class ModActivation:
    def __init__(self, ports: ActivationPorts) -> None:
        self._ports = ports

    def ensure(
        self, mod_id: str, session_id: str | None = None, *, requires_http: bool = True
    ) -> bool:
        """校验并加载 Mod；直接访问 Mod API 时还需挂载 HTTP 路由。"""
        mid = (mod_id or "").strip()
        if not mid or self._ports.disabled():
            return False
        self._ports.restore(session_id)
        if not self._ports.allowed(mid, session_id):
            self._ports.logger.warning("[ModManager] ensure_mod_api_ready: mod %s not allowed", mid)
            return False
        from app.infrastructure.mods.host_backed_routes import is_host_backed_route_mod

        if is_host_backed_route_mod(mid):
            # This route is registered by legacy_compat at host startup, so there
            # is no physical MOD directory to load or report as missing.
            self._ports.clear_missing(mid)
            return True
        mm = self._ports.manager()
        employee_pack_ready = self._ports.employee_ready(
            mm,
            mid,
            registered_pack_ids=self._ports.registered_employees,
            register_routes=self._ports.register_employee,
        )
        if employee_pack_ready is not None:
            return employee_pack_ready
        if mid not in mm._loaded_mods:
            if mm.resolve_mod_directory(mid) is None:
                recovered = False
                try:
                    from app.mod_sdk.industry_seed import (
                        open_industry_seed_mod_ids,
                        seed_industry_mod,
                    )

                    if mid in set(open_industry_seed_mod_ids()):
                        seed_result = seed_industry_mod(mid)
                        recovered = bool(seed_result.get("success"))
                        if recovered:
                            self._ports.clear_missing(mid)
                            self._ports.logger.info(
                                "[ModManager] restored bundled industry seed before API mount: %s",
                                mid,
                            )
                        else:
                            self._ports.logger.warning(
                                "[ModManager] bundled industry seed restore failed for %s: %s",
                                mid,
                                seed_result.get("message") or seed_result.get("status"),
                            )
                except RECOVERABLE_ERRORS as exc:
                    self._ports.logger.warning(
                        "[ModManager] bundled industry seed restore error for %s: %s", mid, exc
                    )
                if not recovered:
                    self._ports.mark_missing(mid)
                    return False
            self._ports.clear_missing(mid)
            if mid not in mm._loaded_mods:
                retry_at = self._ports.retry_at.get(mid, 0.0)
                if retry_at > time.monotonic():
                    self._ports.logger.debug(
                        "[ModManager] ensure_mod_api_ready: load_mod(%s) retry delay active", mid
                    )
                    return False
                if not mm.load_mod(mid):
                    self._ports.retry_at[mid] = time.monotonic() + self._ports.retry_backoff
                    from app.runtime_integrity import record_runtime_issue

                    record_runtime_issue(
                        f"industry_mod:{mid}",
                        f"Industry MOD failed to load: {mid}",
                        ttl_seconds=max(self._ports.retry_backoff * 2, 30.0),
                    )
                    self._ports.logger.warning(
                        "[ModManager] ensure_mod_api_ready: load_mod(%s) failed", mid
                    )
                    return False
                self._ports.retry_at.pop(mid, None)
                self._ports.clear_missing(mid)
        if not requires_http or mid in mm._http_routes_registered:
            return True
        try:
            from app.fastapi_app import get_fastapi_app

            app = get_fastapi_app()
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.warning("ensure_mod_api_ready: cannot get FastAPI app: %s", e)
            return False
        ok = self._ports.register_mod(app, mm, mid)
        if ok:
            from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

            ensure_spa_fallback_last(app)
        return ok

    def entitled_ids(self, session_id: str | None = None) -> list[str]:
        """当前企业会话下允许挂载 API 的客户定制 Mod id（去重、排序）。"""
        try:
            from app.enterprise.mod_entitlements import (
                enterprise_mod_filter_active,
                get_cached_entitled_client_mod_ids,
                is_client_mod_id,
                is_mod_visible_for_enterprise,
            )
        except RECOVERABLE_ERRORS:
            return []
        if not enterprise_mod_filter_active():
            return []
        self._ports.restore(session_id)
        candidates: set[str] = set()
        entitled = get_cached_entitled_client_mod_ids()
        if entitled:
            for mid in entitled:
                token = str(mid or "").strip()
                if token and is_client_mod_id(token) and is_mod_visible_for_enterprise(token):
                    candidates.add(token)
        try:
            from app.mod_sdk.platform_shell import PROTECTED_CLIENT_MOD_IDS

            for mid in PROTECTED_CLIENT_MOD_IDS:
                token = str(mid or "").strip()
                if token and is_mod_visible_for_enterprise(token):
                    candidates.add(token)
        except RECOVERABLE_ERRORS:
            pass
        try:
            from app.mod_sdk.industry_seed import open_industry_seed_mod_ids

            open_seed_ids = set(open_industry_seed_mod_ids())
            mods_root = Path(self._ports.manager().mods_root)
            candidates = {
                mid for mid in candidates if mid not in open_seed_ids or (mods_root / mid).is_dir()
            }
        except RECOVERABLE_ERRORS:
            self._ports.logger.debug("filter unselected open industry seeds skipped", exc_info=True)
        return sorted(candidates)

    def mount_entitled(self, app: FastAPI, session_id: str | None = None) -> list[str]:
        """
        登录后治根：为 entitlement 允许的客户 Mod 执行 load + /api/mod/{id}/* 挂载。

        与冷启动 ``load_all_mods`` 互补——避免无 session 时跳过、登录后仍 404。
        """
        if self._ports.disabled():
            return []
        mounted: list[str] = []
        for mid in self._ports.candidates(session_id):
            if self._ports.ensure(mid, session_id=session_id):
                mounted.append(mid)
        if mounted:
            from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

            ensure_spa_fallback_last(app)
            self._ports.logger.info(
                "[ModManager] mount_entitled_client_mod_api_routes: %s", mounted
            )
        return mounted


def mod_allowed_for_api_load(mod_id: str, session_id: str | None = None) -> bool:
    mid = (mod_id or "").strip()
    if not mid:
        return False
    try:
        from app.enterprise.mod_entitlements import (
            enterprise_mod_filter_active,
            is_mod_visible_for_enterprise,
        )

        if not enterprise_mod_filter_active():
            return True
        if is_mod_visible_for_enterprise(mid):
            return True
    except RECOVERABLE_ERRORS:
        pass
    return False
