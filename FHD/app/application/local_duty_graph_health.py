"""本地编制图 health / 员工 manifest（不代理远端修茈服务器）。"""

from __future__ import annotations

import json
import os
from typing import Any

from app.application.ops_closure_status import _duty_employee_area_map, _installed_employee_pack_ids
from app.mod_sdk.duty_roster import all_planned_duty_employee_ids, load_duty_roster_document
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _local_registered_employee_pack_ids() -> set[str]:
    """本机已安装 employee_pack（编制图「已上架」判定）。"""
    return _installed_employee_pack_ids()


def _staffing_areas_from_doc(doc: dict[str, Any], registered: set[str]) -> list[dict[str, Any]]:
    """从 duty_roster areas 或 departments 生成区段缺岗列表。"""
    areas_out: list[dict[str, Any]] = []
    areas_doc = doc.get("areas") if isinstance(doc.get("areas"), dict) else {}
    if not areas_doc:
        departments = doc.get("departments") if isinstance(doc.get("departments"), dict) else {}
        areas_doc = departments if isinstance(departments, dict) else {}

    def _append_block(key: str, block: dict[str, Any]) -> None:
        raw_ids = block.get("ids")
        ids = (
            [str(x).strip() for x in raw_ids if str(x).strip()] if isinstance(raw_ids, list) else []
        )
        subzones = block.get("subzones")
        if isinstance(subzones, dict):
            for sub_key, sub in subzones.items():
                if isinstance(sub, dict):
                    _append_block(f"{key}/{sub_key}", sub)
        if ids:
            areas_out.append(
                {
                    "key": str(key),
                    "label": str(block.get("label") or key),
                    "missing": sorted(set(ids) - registered),
                }
            )

    for key, block in areas_doc.items():
        if isinstance(block, dict):
            _append_block(str(key), block)
    return areas_out


def build_local_duty_graph_health() -> dict[str, Any]:
    """与 MODstore ``/api/admin/duty-graph/health`` staffing 字段对齐，数据源为本机。"""
    from app.application.employee_runtime.scheduler import get_employee_scheduler_status

    planned = sorted(all_planned_duty_employee_ids())
    registered = _local_registered_employee_pack_ids()
    planned_set = set(planned)
    missing_local = sorted(planned_set - registered)
    area_map = _duty_employee_area_map()
    doc = load_duty_roster_document()
    areas = _staffing_areas_from_doc(doc, registered)
    scheduler = get_employee_scheduler_status()

    return {
        "success": True,
        "source": "local",
        "staffing": {
            "planned_count": len(planned),
            "registered_count": len(planned_set & registered),
            # 本地 health：编制内员工仍在 roster/catalog 语义下展示；勿把「未落盘」当成「未进 catalog」
            "missing_employees": [],
            "missing_local_employee_packs": missing_local,
            "extra_employees": sorted(registered - planned_set),
            "areas": areas,
            "area_map_size": len(area_map),
        },
        "change_requests": {"pending": 0, "failed": 0},
        "employee_cron_jobs": scheduler.get("jobs", []),
        "employee_scheduler": {
            "enabled": scheduler.get("enabled", False),
            "running": scheduler.get("running", False),
            "last_error": scheduler.get("last_error", ""),
        },
        "incident_unknown_24h": 0,
        "env_flags": {
            "MODSTORE_DAILY_ORCHESTRATOR_ENABLED": os.environ.get(
                "MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "1"
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
        # 遍历所有 mods search roots，避免主 mods_root 副本残缺时读不到 manifest
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
    except RECOVERABLE_ERRORS:
        pass
    return None


def build_local_employee_status(employee_id: str) -> dict[str, Any]:
    """本地无远端执行审计时返回空统计，供编制图 Phase2 渲染。"""
    from app.application.employee_runtime.metrics import get_employee_runtime_metrics

    pid = str(employee_id or "").strip()
    manifest = read_local_employee_manifest(pid)
    deployed = manifest is not None
    metrics = get_employee_runtime_metrics()
    row = dict((metrics.get("by_employee") or {}).get(pid) or {})
    total = int(row.get("runs_total") or 0)
    success_count = int(row.get("runs_success") or 0)
    success_rate = round(success_count / total, 4) if total else 0
    return {
        "employee_id": pid,
        "deployed": deployed,
        "last_execution": row.get("last_execution"),
        "execution_stats": {
            "total_executions": total,
            "success_count": success_count,
            "failed_count": int(row.get("runs_failed") or 0),
            "blocked_count": int(row.get("runs_blocked") or 0),
            "success_rate": success_rate,
        },
    }


__all__ = [
    "build_local_duty_graph_health",
    "build_local_employee_status",
    "read_local_employee_manifest",
]
