"""ModuleCatalog control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .ports import ErrorPolicy, JsonObject


class ModuleCatalog:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        release_train_snapshot: Callable[[], JsonObject],
        core_modules: Callable[[], list[JsonObject]],
        collect_employee_pack_modules: Callable[[], list[JsonObject]],
        collect_mod_modules: Callable[[], list[JsonObject]],
        config_root: Callable[[], Path],
    ) -> None:
        self._errors = errors
        self._call_release_train_snapshot = release_train_snapshot
        self._core_modules = core_modules
        self._call_collect_employee_pack_modules = collect_employee_pack_modules
        self._call_collect_mod_modules = collect_mod_modules
        self._config_root = config_root

    def _release_train_snapshot(self) -> dict[str, Any]:
        """读取 release_train SSOT；优先 modstore 模块，回退 FHD/config JSON。"""
        from pathlib import Path

        def _default_snapshot(*, note: str | None = None) -> dict[str, Any]:
            data: dict[str, Any] = {
                "epoch": "1.0.0.0",
                "current": "1.0.0.1",
                "started_at": "2026-06-04",
                "day_index": 0,
            }
            if note:
                data["note"] = note
            return data

        def _from_file(path: Path) -> dict[str, Any]:
            if not path.is_file():
                return _default_snapshot(note="ssot missing")
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except self._errors.recoverable() as exc:
                self._errors.logger.warning("release-train json read failed: %s", exc)
            return _default_snapshot()

        mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
        if mono:
            path = Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
            return _from_file(path)
        try:
            from modstore_server.release_train import snapshot_public

            return cast("dict[str, Any]", snapshot_public())
        except self._errors.recoverable():
            pass
        path = self._config_root() / "config" / "release_train.json"
        return _from_file(path)

    async def get_release_train(self):
        """release_train 四段 SSOT 快照（全景页 live 刷新，无需登录）。"""
        return {"success": True, "data": self._call_release_train_snapshot()}

    def _collect_mod_modules(self) -> list[dict[str, Any]]:
        """从 mod_manager 读取已加载的本地 Mod，转换成 XCmax 模块格式。"""
        rows: list[dict[str, Any]] = []
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager

            mgr = get_mod_manager()
            if mgr is None:
                return rows
            registry = getattr(mgr, "_registry", None) or {}
            for mod_id, meta in registry.items() if hasattr(registry, "items") else []:
                name = str(getattr(meta, "name", None) or mod_id).strip()
                version = str(getattr(meta, "version", None) or "").strip()
                rows.append(
                    {
                        "module_id": str(mod_id),
                        "display_name": name,
                        "route": f"/mod/{mod_id}",
                        "source": "local",
                        "sync_scope": "module_info",
                        "active": True,
                        "version": version,
                    }
                )
        except self._errors.recoverable() as exc:
            self._errors.logger.debug("collect_mod_modules failed: %s", exc)
        return rows

    def _collect_employee_pack_modules(self) -> list[dict[str, Any]]:
        """从员工包注册表读取员工包，转换成 XCmax 模块格式。"""
        rows: list[dict[str, Any]] = []
        try:
            from app.infrastructure.mods.employee_registry import EmployeeRegistry
            from app.infrastructure.mods.mod_manager import get_mod_manager

            mgr = get_mod_manager()
            mods_root = getattr(mgr, "mods_root", None) if mgr else None
            if mods_root:
                registry = EmployeeRegistry(mods_root)
                for pack in registry.list_packs():
                    pack_id = str(pack.get("id") or "")
                    name = str(pack.get("name") or pack_id).strip()
                    rows.append(
                        {
                            "module_id": pack_id,
                            "display_name": name,
                            "route": "",
                            "source": "employee",
                            "sync_scope": "employee_pack",
                            "active": True,
                            "version": str(pack.get("version") or ""),
                        }
                    )
        except self._errors.recoverable() as exc:
            self._errors.logger.debug("collect_employee_pack_modules failed: %s", exc)
        return rows

    async def list_modules(self):
        """获取 XCmax 模块注册表（核心 + 本地 Mod + 员工包）。"""
        modules: list[dict[str, Any]] = list(self._core_modules())
        modules.extend(self._call_collect_mod_modules())
        modules.extend(self._call_collect_employee_pack_modules())
        return {"success": True, "data": modules, "total": len(modules)}
