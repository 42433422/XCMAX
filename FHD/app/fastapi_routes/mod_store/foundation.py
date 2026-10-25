"""Seed the packaged host and delegate edition policy to its canonical owner."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, cast

from fastapi import HTTPException

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .port_contracts import FoundationInstall
from .schemas import ModStoreInstallResult, ModStoreSimpleResponse


async def ensure_employee_on_disk() -> tuple[bool, str]:
    """将内置 _employees/xcagi-host-foundation-employee 复制到用户 mods 目录（若尚未存在）。"""
    import shutil
    import sys

    from app.infrastructure.mods.employee_registry import employees_root, get_employee_registry
    from app.mod_sdk.host_foundation import HOST_FOUNDATION_EMPLOYEE_PACK_ID

    mm_root = get_employee_registry().mods_root
    dest = os.path.join(employees_root(mm_root), HOST_FOUNDATION_EMPLOYEE_PACK_ID)
    if os.path.isdir(dest):
        return (True, "employee pack present")
    candidates = [Path(mm_root) / "_employees" / HOST_FOUNDATION_EMPLOYEE_PACK_ID]
    if (
        getattr(sys, "frozen", False)
        or os.environ.get("XCAGI_BUNDLED_MODS_DIR")
        or os.environ.get("XCAGI_SEED_MODS_DIR")
    ):
        from app.mod_sdk.edition_policy import bundled_mods_dir

        bundled = bundled_mods_dir()
        if bundled is not None:
            candidates.append(Path(bundled) / "_employees" / HOST_FOUNDATION_EMPLOYEE_PACK_ID)
    src = next((p for p in candidates if os.path.isdir(str(p))), None)
    if src is None:
        checked = "；".join(str(p) for p in candidates)
        return (False, f"内置员工包目录缺失：{checked}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest)
    return (True, "employee pack seeded")


def can_materialize_without_marker() -> bool:
    """Packaged builds can seed host bridges without the employee marker pack."""
    import sys

    return bool(
        getattr(sys, "frozen", False)
        or os.environ.get("XCAGI_BUNDLED_MODS_DIR")
        or os.environ.get("XCAGI_SEED_MODS_DIR")
    )


class HostFoundation:
    def __init__(
        self,
        ensure: Callable[[], Awaitable[tuple[bool, str]]],
        can_materialize: Callable[[], bool],
        install: FoundationInstall,
        logger: logging.Logger,
    ) -> None:
        self._ensure = ensure
        self._can_materialize = can_materialize
        self._install = install
        self._logger = logger

    async def install(self, edition: str | None) -> ModStoreInstallResult:
        from app.mod_sdk.edition_policy import resolve_edition
        from app.mod_sdk.host_foundation import materialize_host_foundation_bridges

        ok, msg = await self._ensure()
        employee_seed_warning = ""
        if not ok:
            if not self._can_materialize():
                return ModStoreInstallResult(success=False, message=msg, data=None)
            employee_seed_warning = msg
        ed = (edition or resolve_edition() or "generic").strip().lower()
        if ed not in ("minimal", "generic", "full"):
            ed = "generic"
        try:
            data = materialize_host_foundation_bridges(ed)
        except RECOVERABLE_ERRORS as exc:
            self._logger.exception("materialize_host_foundation_bridges failed (edition=%s)", ed)
            return ModStoreInstallResult(
                success=False,
                message=f"展开宿主 bridge 失败：{exc}",
                data={"edition": ed, "missing_mod_ids": [], "ready": False},
            )
        if employee_seed_warning and isinstance(data, dict):
            data = {**data, "employee_seed_warning": employee_seed_warning}
        if data.get("ready"):
            message = f"宿主基础能力员工包已就绪（bridge {data.get('installed_count')}/{data.get('expected_count')}）"
            if employee_seed_warning:
                message += f"；员工包标记未复制（{employee_seed_warning}）"
            success = True
        else:
            missing = data.get("missing_mod_ids") or []
            message = f"宿主 bridge 未齐（{data.get('installed_count')}/{data.get('expected_count')}）：{'、'.join(missing[:8])}"
            success = False
        return ModStoreInstallResult(success=success, message=message, data=data)

    async def install_response(self, edition: str | None = None) -> ModStoreSimpleResponse:
        """安装「宿主基础能力·预装员工」并 materialize 全部 bridge（非逐项 Mod 上架）。"""
        try:
            result = await self._install(edition)
            return ModStoreSimpleResponse(
                success=result.success, message=result.message, data=result.data
            )
        except RECOVERABLE_ERRORS as exc:
            self._logger.exception("install-host-foundation failed")
            return ModStoreSimpleResponse(success=False, message=f"装包失败：{exc}", data=None)

    async def bootstrap(self, edition: str | None = None) -> ModStoreSimpleResponse:
        """装齐当前 edition 所需 Mod：先复制安装包内置 mods/，再对缺失项尝试 Catalog。"""
        from app.mod_sdk.edition_bootstrap import bootstrap_edition_pack
        from app.mod_sdk.edition_policy import resolve_edition

        ed = (edition or resolve_edition() or "generic").strip().lower()
        if ed not in ("minimal", "generic", "full"):
            raise HTTPException(status_code=400, detail="edition 须为 minimal、generic 或 full")
        try:
            from app.mod_sdk.product_skus import assert_bootstrap_edition_allowed

            assert_bootstrap_edition_allowed(edition)
        except PermissionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data = await bootstrap_edition_pack(cast("Literal['minimal', 'generic', 'full']", ed))
        if data.get("ready"):
            msg = "通用宿主包已装齐"
        else:
            installed = int(data.get("installed_count") or 0)
            expected = int(data.get("expected_count") or 0)
            failed_ids: list[str] = []
            for row in data.get("catalog") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("status") in ("catalog_failed", "missing"):
                    mid = str(row.get("mod_id") or "").strip()
                    if mid:
                        failed_ids.append(mid)
            for row in data.get("seed") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("status") in ("missing", "error"):
                    mid = str(row.get("mod_id") or "").strip()
                    if mid and mid not in failed_ids:
                        failed_ids.append(mid)
            hint = "、".join(failed_ids[:8])
            msg = f"宿主包未装齐（{installed}/{expected}）"
            if hint:
                msg += f"：{hint}"
        return ModStoreSimpleResponse(success=bool(data.get("ready")), message=msg, data=data)
