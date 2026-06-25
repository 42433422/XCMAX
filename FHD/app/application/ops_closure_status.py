"""运维闭环状态聚合：MODstore 值班 health + 本地 employee_pack 安装对照。"""

from __future__ import annotations

from typing import Any

from app.mod_sdk.duty_roster import all_planned_duty_employee_ids, load_duty_roster_document
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _installed_employee_pack_ids() -> set[str]:
    """扫描所有 mods search roots 下的 `_employees/`，避免主 mods_root 副本残缺时误报缺岗。"""
    ids: set[str] = set()
    try:
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        # 主 mods_root + 仓库内其它 mods 目录（去重，主目录优先）
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except RECOVERABLE_ERRORS:
            pass
        if not roots:
            primary = getattr(mgr, "mods_root", None)
            if primary:
                roots = [primary]
        for mods_root in roots:
            if not mods_root:
                continue
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                pid = str(pack.get("id") or "").strip()
                if pid:
                    ids.add(pid)
    except RECOVERABLE_ERRORS:
        pass
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        for mod in mm.list_loaded_mods() or []:
            if str(getattr(mod, "artifact", "") or "").strip().lower() == "employee_pack":
                pid = str(getattr(mod, "id", "") or "").strip()
                if pid:
                    ids.add(pid)
    except RECOVERABLE_ERRORS:
        pass
    return ids


def _duty_employee_area_map() -> dict[str, dict[str, str]]:
    areas = load_duty_roster_document().get("areas") or {}
    out: dict[str, dict[str, str]] = {}
    if not isinstance(areas, dict):
        return out
    for key, block in areas.items():
        if not isinstance(block, dict):
            continue
        label = str(block.get("label") or key).strip() or key
        raw_ids = block.get("ids")
        if not isinstance(raw_ids, list):
            continue
        for pid in raw_ids:
            employee_id = str(pid or "").strip()
            if employee_id:
                out[employee_id] = {"area_key": str(key), "area_label": label}
    return out


def _build_roster_rows(
    planned: list[str],
    *,
    missing_remote_set: set[str],
    local_packs: set[str],
    area_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for employee_id in planned:
        in_catalog = employee_id not in missing_remote_set
        local_installed = employee_id in local_packs
        area = area_map.get(employee_id) or {}
        rows.append(
            {
                "id": employee_id,
                "area_key": area.get("area_key", ""),
                "area_label": area.get("area_label", ""),
                "in_catalog": in_catalog,
                "local_installed": local_installed,
                "needs_action": (not in_catalog) or (in_catalog and not local_installed),
            }
        )
    return rows


def build_ops_closure_status(remote_health: dict[str, Any] | None) -> dict[str, Any]:
    health = remote_health if isinstance(remote_health, dict) else {}
    staffing = health.get("staffing") if isinstance(health.get("staffing"), dict) else {}
    missing_remote = list(staffing.get("missing_employees") or [])
    missing_remote_set = set(missing_remote)
    planned = sorted(all_planned_duty_employee_ids())
    local_packs = _installed_employee_pack_ids()
    registered = [pid for pid in planned if pid not in missing_remote_set]
    missing_local = [pid for pid in registered if pid not in local_packs]
    area_map = _duty_employee_area_map()
    roster_rows = _build_roster_rows(
        planned,
        missing_remote_set=missing_remote_set,
        local_packs=local_packs,
        area_map=area_map,
    )
    cr = health.get("change_requests") if isinstance(health.get("change_requests"), dict) else {}
    blockers: list[dict[str, Any]] = []
    if missing_remote:
        blockers.append(
            {
                "code": "REMOTE_STAFFING_GAP",
                "count": len(missing_remote),
                "employee_ids": missing_remote[:50],
            }
        )
    if missing_local:
        blockers.append(
            {
                "code": "LOCAL_EMPLOYEE_PACK_MISSING",
                "count": len(missing_local),
                "employee_ids": missing_local[:50],
            }
        )
    pending_cr = int(cr.get("pending") or 0)
    if pending_cr > 0:
        blockers.append({"code": "PENDING_CHANGE_REQUESTS", "count": pending_cr})
    deliverable = not missing_remote and pending_cr == 0
    staffing_local = {
        **staffing,
        "planned_count": len(planned),
        "registered_count": len(registered),
        "missing_employees": missing_remote,
        "remote_planned_count": staffing.get("planned_count"),
        "remote_registered_count": staffing.get("registered_count"),
    }
    planned_local_installed = [pid for pid in planned if pid in local_packs]
    extra_local_packs = sorted(local_packs - set(planned))
    return {
        "deliverable": deliverable,
        "remote_health": health,
        "staffing": staffing_local,
        "planned_employee_ids": planned,
        "registered_employee_ids": registered,
        "local_employee_pack_ids": sorted(local_packs),
        "planned_local_installed_count": len(planned_local_installed),
        "extra_local_employee_pack_ids": extra_local_packs,
        "missing_remote_employees": missing_remote,
        "missing_local_employee_packs": missing_local,
        "roster_rows": roster_rows,
        "blockers": blockers,
        "next_actions": _next_actions(missing_remote, missing_local, pending_cr),
    }


def _next_actions(
    missing_remote: list[str], missing_local: list[str], pending_cr: int
) -> list[str]:
    actions: list[str] = []
    if missing_remote:
        actions.append("POST /api/xcmax/ops/staffing/onboard 补登记编制员工到 Catalog")
    if missing_local:
        actions.append("POST /api/xcmax/ops/staffing/install-local 将已上架员工包装到本地")
    if pending_cr:
        actions.append("在 MODstore 管理员页处理待审 Change Request")
    if not actions:
        actions.append("编制与本地安装均已就绪，可下达运维任务")
    return actions


__all__ = ["build_ops_closure_status"]
