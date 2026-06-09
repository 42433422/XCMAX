"""本地编制图 health / 员工 manifest（不代理远端修茈服务器）。"""

from __future__ import annotations

import json
import os
from typing import Any

from app.application.ops_closure_status import _duty_employee_area_map, _installed_employee_pack_ids
from app.mod_sdk.duty_roster import all_planned_duty_employee_ids, load_duty_roster_document
from app.utils.operational_errors import OPERATIONAL_ERRORS


def _local_registered_employee_pack_ids() -> set[str]:
    """本机已安装 employee_pack（编制图「已上架」判定）。"""
    return _installed_employee_pack_ids()


def build_local_duty_graph_health() -> dict[str, Any]:
    """与 MODstore ``/api/admin/duty-graph/health`` staffing 字段对齐，数据源为本机。"""
    planned = sorted(all_planned_duty_employee_ids())
    registered = _local_registered_employee_pack_ids()
    planned_set = set(planned)
    missing = sorted(planned_set - registered)
    area_map = _duty_employee_area_map()
    doc = load_duty_roster_document()
    areas_doc = doc.get("areas") if isinstance(doc.get("areas"), dict) else {}

    areas: list[dict[str, Any]] = []
    if isinstance(areas_doc, dict):
        for key, block in areas_doc.items():
            if not isinstance(block, dict):
                continue
            raw_ids = block.get("ids")
            ids = (
                [str(x).strip() for x in raw_ids if str(x).strip()]
                if isinstance(raw_ids, list)
                else []
            )
            areas.append(
                {
                    "key": str(key),
                    "label": str(block.get("label") or key),
                    "missing": sorted(set(ids) - registered),
                }
            )

    return {
        "success": True,
        "source": "local",
        "staffing": {
            "planned_count": len(planned),
            "registered_count": len(planned_set & registered),
            "missing_employees": missing,
            "extra_employees": sorted(registered - planned_set),
            "areas": areas,
            "area_map_size": len(area_map),
        },
        "change_requests": {"pending": 0, "failed": 0},
        "employee_cron_jobs": [],
        "incident_unknown_24h": 0,
        "env_flags": {
            "MODSTORE_DAILY_ORCHESTRATOR_ENABLED": os.environ.get(
                "MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "0"
            ),
            "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED": os.environ.get(
                "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1"
            ),
        },
    }


def read_local_employee_manifest(employee_id: str) -> dict[str, Any] | None:
    pid = str(employee_id or "").strip()
    if not pid:
        return None
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        mods_root = getattr(mgr, "mods_root", None)
        if mods_root:
            mf_path = os.path.join(os.path.abspath(mods_root), "_employees", pid, "manifest.json")
            if os.path.isfile(mf_path):
                with open(mf_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "employee_id": pid,
                        "manifest": data,
                        **data,
                    }
    except OPERATIONAL_ERRORS:
        pass
    return None


def build_local_employee_status(employee_id: str) -> dict[str, Any]:
    """本地无远端执行审计时返回空统计，供编制图 Phase2 渲染。"""
    pid = str(employee_id or "").strip()
    manifest = read_local_employee_manifest(pid)
    deployed = manifest is not None
    return {
        "employee_id": pid,
        "deployed": deployed,
        "last_execution": None,
        "execution_stats": {
            "total_executions": 0,
            "success_count": 0,
            "success_rate": 0,
        },
    }


__all__ = [
    "build_local_duty_graph_health",
    "build_local_employee_status",
    "read_local_employee_manifest",
]
