"""Project installed metadata for the current enterprise's frontend visibility."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..artifact_constants import ARTIFACT_BUNDLE, normalize_artifact
from ..manifest import ModMetadata
from .ports import Payload


@dataclass(frozen=True)
class ViewPorts:
    disabled: Callable[[], bool]
    refresh: Callable[[], None]
    root: Callable[[], str]
    scan: Callable[[], list[ModMetadata]]
    project: Callable[[ModMetadata], Payload]
    logger: logging.Logger


class ModViews:
    def __init__(self, ports: ViewPorts) -> None:
        self._ports = ports

    def list_all(self) -> list[Payload]:
        """返回已通过账号权益过滤的已安装 Mod，包含尚未加载的包。"""
        if self._ports.disabled():
            return []
        self._ports.refresh()
        rows = [self._ports.project(x) for x in self._ports.scan()]
        try:
            from ..employee_registry import get_employee_registry

            rows = rows + get_employee_registry(self._ports.root()).list_for_mods_api()
        except RECOVERABLE_ERRORS as e:
            self._ports.logger.warning("employee registry merge skipped: %s", e)
        try:
            from app.enterprise.mod_entitlements import filter_mod_rows_for_enterprise

            rows = filter_mod_rows_for_enterprise(rows)
        except RECOVERABLE_ERRORS:
            return []
        return rows

    def routes(self) -> list[dict[str, str]]:
        """
        返回含 mod_id 的条目，供前端 registerModRoutes 匹配 Vite glob。
        manifest frontend.routes 非空即视为存在 frontend/routes.js（或约定路径）。
        """
        if self._ports.disabled():
            return []
        self._ports.refresh()
        out: list[dict[str, str]] = []
        for m in self._ports.scan():
            try:
                from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

                if not is_mod_visible_for_enterprise(m.id):
                    continue
            except RECOVERABLE_ERRORS:
                continue
            rp = (m.frontend_routes or "").strip()
            if rp:
                out.append({"mod_id": m.id, "routes_path": rp})
        return out


def metadata_to_api_dict(m: ModMetadata) -> Payload:
    """与前端 /api/mods/ 列表项、侧栏 manifest 展示字段对齐。"""
    art = normalize_artifact({"artifact": m.artifact})
    row: Payload = {
        "id": m.id,
        "name": m.name,
        "version": m.version,
        "author": m.author or "",
        "description": m.description or "",
        "primary": bool(m.primary),
        "artifact": art,
        "scope": m.scope,
        "industry": dict(m.industry) if isinstance(m.industry, dict) else {},
        "ui_labels": dict(m.ui_labels) if isinstance(m.ui_labels, dict) else {},
        "ui_starter_pack": list(m.ui_starter_pack) if isinstance(m.ui_starter_pack, list) else [],
        "menu": list(m.frontend_menu) if m.frontend_menu else [],
        "frontend": {
            "pro_entry_path": str(getattr(m, "frontend_pro_entry_path", "") or "").strip(),
            "runtime": dict(m.frontend_runtime),
        },
        "menu_overrides": list(m.frontend_menu_overrides) if m.frontend_menu_overrides else [],
        "workflow_employees": list(m.workflow_employees) if m.workflow_employees else [],
        "comms_exports": list(m.comms_exports) if m.comms_exports else [],
    }
    if art == ARTIFACT_BUNDLE:
        row["type"] = "bundle"
    return row
