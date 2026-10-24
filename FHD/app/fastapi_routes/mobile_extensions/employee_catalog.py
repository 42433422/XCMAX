"""EmployeeCatalog: explicit collaborators for one mobile capability."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.fastapi_routes.mobile_extensions.ports import (
    AdminDutyModItemCall,
    AdminDutyRecordsFromRosterCall,
    AdminEmployeeItemsCall,
    AdminEmployeeManifestCall,
    AdminEmployeeMatchKeysCall,
    AdminRosterAreaLabelsCall,
    AdminRosterIdsByDepartmentOrderCall,
    ApplyMarketProfileCall,
    CompactTextCall,
    DutyRosterCall,
    EmployeeSsotCall,
    EnrichWorkflowEmployeesCall,
    InstalledEmployeeIdsCall,
    LoadAdminDutyRecordsCall,
    MobileModItemsCall,
    ModManagerCall,
    RosterDocumentCall,
    UpsertAdminDutyModItemCall,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmployeeCatalogPorts:
    enrich_workflow_employees: EnrichWorkflowEmployeesCall
    upsert_admin_duty_mod_item: UpsertAdminDutyModItemCall
    mod_manager: ModManagerCall
    duty_roster: DutyRosterCall
    compact_text: CompactTextCall
    roster_document: RosterDocumentCall
    admin_employee_manifest: AdminEmployeeManifestCall
    admin_roster_area_labels: AdminRosterAreaLabelsCall
    admin_roster_ids_by_department_order: AdminRosterIdsByDepartmentOrderCall
    load_admin_duty_records: LoadAdminDutyRecordsCall
    admin_duty_records_from_roster: AdminDutyRecordsFromRosterCall
    admin_employee_match_keys: AdminEmployeeMatchKeysCall
    apply_market_profile: ApplyMarketProfileCall
    admin_employee_items: AdminEmployeeItemsCall
    admin_duty_mod_item: AdminDutyModItemCall
    mobile_mod_items: MobileModItemsCall
    installed_employee_ids: InstalledEmployeeIdsCall
    employee_ssot: EmployeeSsotCall


class EmployeeCatalog:
    def __init__(self, ports: EmployeeCatalogPorts) -> None:
        self.ports = ports

        def _mobile_mod_items(
            market_profiles: dict[str, dict[str, Any]] | None = None,
            *,
            market_connected: bool = False,
        ) -> list[dict[str, Any]]:
            try:
                items: list[dict[str, Any]] = []
                for m in ports.mod_manager().list_all_mods() or []:
                    if isinstance(m, dict):
                        mid = str(m.get("id") or m.get("mod_id") or "").strip()
                        name = str(m.get("name") or m.get("title") or mid).strip()
                        raw_employees = m.get("workflow_employees")
                        employees: list[Any] = (
                            raw_employees if isinstance(raw_employees, list) else []
                        )
                        menu = m.get("frontend_menu") or m.get("menu") or m.get("menus")
                        menu_overrides = m.get("menu_overrides")
                        item: dict[str, Any] = {
                            "id": mid,
                            "name": name,
                            "version": m.get("version") or "",
                            "author": m.get("author") or "",
                            "description": m.get("description") or "",
                            "primary": bool(m.get("primary")),
                            "industry": m.get("industry")
                            if isinstance(m.get("industry"), dict)
                            else {},
                            "avatar_url": m.get("avatar") or m.get("logo") or m.get("icon") or "",
                            "frontend_menu": menu if isinstance(menu, list) else [],
                            "menu": menu if isinstance(menu, list) else [],
                            "menu_overrides": menu_overrides
                            if isinstance(menu_overrides, list)
                            else [],
                            "workflow_employees": ports.enrich_workflow_employees(
                                mid, employees, market_profiles, market_connected=market_connected
                            ),
                        }
                    else:
                        mid = str(getattr(m, "id", None) or getattr(m, "mod_id", "") or "").strip()
                        name = str(
                            getattr(m, "name", None) or getattr(m, "title", None) or mid
                        ).strip()
                        employees = getattr(m, "workflow_employees", [])
                        if not isinstance(employees, list):
                            employees = []
                        menu = getattr(m, "frontend_menu", [])
                        menu_overrides = getattr(m, "frontend_menu_overrides", [])
                        item = {
                            "id": mid,
                            "name": name,
                            "version": str(getattr(m, "version", "") or ""),
                            "author": str(getattr(m, "author", "") or ""),
                            "description": str(getattr(m, "description", "") or ""),
                            "primary": bool(getattr(m, "primary", False)),
                            "industry": getattr(m, "industry", {})
                            if isinstance(getattr(m, "industry", {}), dict)
                            else {},
                            "avatar_url": str(
                                getattr(m, "avatar", "")
                                or getattr(m, "logo", "")
                                or getattr(m, "icon", "")
                                or ""
                            ),
                            "frontend_menu": menu if isinstance(menu, list) else [],
                            "menu": menu if isinstance(menu, list) else [],
                            "menu_overrides": menu_overrides
                            if isinstance(menu_overrides, list)
                            else [],
                            "workflow_employees": ports.enrich_workflow_employees(
                                mid, employees, market_profiles, market_connected=market_connected
                            ),
                        }
                    if mid:
                        items.append(item)
                ports.upsert_admin_duty_mod_item(
                    items, market_profiles, market_connected=market_connected
                )
                return items[:100]
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile mods list: %s", exc)
                items = []
                ports.upsert_admin_duty_mod_item(
                    items, market_profiles, market_connected=market_connected
                )
                return items

        self._mobile_mod_items = _mobile_mod_items

        def _admin_roster_ids_by_department_order() -> list[str]:
            try:
                admin = ports.duty_roster()
            except RECOVERABLE_ERRORS:
                return []
            seen: set[str] = set()
            out: list[str] = []
            for dept in admin.get("departments") or []:
                if not isinstance(dept, dict):
                    continue
                for employee in dept.get("employees") or []:
                    if not isinstance(employee, dict):
                        continue
                    eid = str(employee.get("id") or "").strip()
                    if eid and eid not in seen:
                        seen.add(eid)
                        out.append(eid)
            for eid in admin.get("planned_employee_ids") or []:
                eid = str(eid or "").strip()
                if eid and eid not in seen:
                    seen.add(eid)
                    out.append(eid)
            return out

        self._admin_roster_ids_by_department_order = _admin_roster_ids_by_department_order

        def _admin_roster_area_labels() -> dict[str, str]:
            try:
                doc = ports.roster_document()
            except RECOVERABLE_ERRORS:
                return {}
            out: dict[str, str] = {}
            areas = doc.get("areas") if isinstance(doc, dict) else {}
            if not isinstance(areas, dict):
                return out
            for _area_key, area in areas.items():
                if not isinstance(area, dict):
                    continue
                label = ports.compact_text(area.get("label"))
                for eid in area.get("ids") or []:
                    sid = str(eid or "").strip()
                    if sid and label and (sid not in out):
                        out[sid] = label
            return out

        self._admin_roster_area_labels = _admin_roster_area_labels

        def _admin_employee_manifest(employee_id: str) -> dict[str, Any]:
            eid = str(employee_id or "").strip()
            if not eid:
                return {}
            manifest = (
                Path(__file__).resolve().parents[3] / "mods" / "_employees" / eid / "manifest.json"
            )
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
                return raw if isinstance(raw, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}

        self._admin_employee_manifest = _admin_employee_manifest

        def _admin_duty_records_from_roster() -> list[dict[str, Any]]:
            registry = ports.load_admin_duty_records()
            roster_ids = ports.admin_roster_ids_by_department_order()
            if not roster_ids:
                return registry
            registry_by_id: dict[str, dict[str, Any]] = {}
            for raw in registry:
                eid = str(raw.get("id") or raw.get("pkg_id") or "").strip()
                if eid and eid not in registry_by_id:
                    registry_by_id[eid] = raw
            registry_ids = set(registry_by_id)
            roster_id_set = set(roster_ids)
            if registry_ids and (not registry_ids & roster_id_set):
                return registry
            area_labels = ports.admin_roster_area_labels()
            records: list[dict[str, Any]] = []
            for eid in roster_ids:
                raw = dict(registry_by_id.get(eid) or {})
                manifest: dict[str, Any] = dict(ports.admin_employee_manifest(eid) or {})
                raw_employee_meta = manifest.get("employee")
                employee_meta: dict[str, Any] = (
                    raw_employee_meta if isinstance(raw_employee_meta, dict) else {}
                )
                raw.setdefault("id", eid)
                raw.setdefault("pkg_id", eid)
                raw.setdefault("name", manifest.get("name") or employee_meta.get("label") or eid)
                raw.setdefault("description", manifest.get("description") or "")
                raw.setdefault("version", manifest.get("version") or "")
                raw.setdefault("yuangon_area", area_labels.get(eid, ""))
                raw.setdefault("employee_scope", "duty")
                raw.setdefault("employee_source", "duty_roster")
                raw.setdefault("is_duty_employee", True)
                raw.setdefault("is_store_employee", False)
                records.append(raw)
            return records

        self._admin_duty_records_from_roster = _admin_duty_records_from_roster

        def _admin_employee_items(
            market_profiles: dict[str, dict[str, Any]] | None = None,
            *,
            market_connected: bool = False,
            im_summary: dict[str, dict[str, Any]] | None = None,
        ) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for raw in ports.admin_duty_records_from_roster():
                employee_id = str(raw.get("id") or raw.get("pkg_id") or "").strip()
                if not employee_id:
                    continue
                name = ports.compact_text(raw.get("name") or employee_id)
                area = ports.compact_text(raw.get("yuangon_area") or raw.get("industry"))
                item = {
                    "id": employee_id,
                    "name": name,
                    "label": name,
                    "title": name,
                    "panel_title": name,
                    "description": ports.compact_text(raw.get("description")),
                    "panel_summary": ports.compact_text(raw.get("description")),
                    "version": str(raw.get("version") or "").strip(),
                    "industry": ports.compact_text(raw.get("industry")),
                    "yuangon_area": area,
                    "employee_scope": ports.compact_text(raw.get("employee_scope") or "duty"),
                    "employee_source": ports.compact_text(
                        raw.get("employee_source") or "duty_roster"
                    ),
                    "is_duty_employee": bool(raw.get("is_duty_employee", True)),
                    "is_store_employee": bool(raw.get("is_store_employee", False)),
                    "status": "on_duty",
                    "api_base_path": f"/api/admin/employees/{employee_id}",
                    "phone_channel": "admin-duty",
                    "workflow_placeholder": False,
                    "stored_filename": ports.compact_text(raw.get("stored_filename")),
                    "file_size": raw.get("file_size") or 0,
                }
                profile = None
                if market_profiles:
                    for key in ports.admin_employee_match_keys(raw, employee_id, name):
                        profile = market_profiles.get(key)
                        if profile:
                            break
                ports.apply_market_profile(item, profile, market_connected=market_connected)
                if im_summary:
                    summary = im_summary.get(employee_id)
                    if summary:
                        item.update(summary)
                items.append(item)
            return items

        self._admin_employee_items = _admin_employee_items

        def _admin_duty_mod_item(
            market_profiles: dict[str, dict[str, Any]] | None = None,
            *,
            market_connected: bool = False,
        ) -> dict[str, Any] | None:
            employees = ports.admin_employee_items(
                market_profiles, market_connected=market_connected
            )
            if not employees:
                return None
            return {
                "id": "admin-duty-employees",
                "name": "管理端编制员工",
                "version": "local",
                "author": "XCAGI 管理端",
                "description": f"{len(employees)} 位管理端编制 AI 员工，来自 duty_roster.json。",
                "primary": True,
                "industry": {"id": "管理端", "name": "管理端"},
                "frontend_menu": [],
                "menu": [],
                "menu_overrides": [],
                "workflow_employees": employees,
            }

        self._admin_duty_mod_item = _admin_duty_mod_item

        def _upsert_admin_duty_mod_item(
            items: list[dict[str, Any]],
            market_profiles: dict[str, dict[str, Any]] | None = None,
            *,
            market_connected: bool = False,
        ) -> None:
            duty_mod = ports.admin_duty_mod_item(market_profiles, market_connected=market_connected)
            if not duty_mod:
                return
            duty_id = str(duty_mod.get("id") or "")
            for item in items:
                if str(item.get("id") or "") != duty_id:
                    continue
                if not item.get("workflow_employees"):
                    item["workflow_employees"] = duty_mod["workflow_employees"]
                return
            items.insert(0, duty_mod)

        self._upsert_admin_duty_mod_item = _upsert_admin_duty_mod_item

        def _ai_circle_employee_profiles() -> dict[str, dict[str, str]]:
            profiles: dict[str, dict[str, str]] = {}
            for mod in ports.mobile_mod_items():
                mod_avatar = str(mod.get("avatar_url") or "").strip()
                for employee in mod.get("workflow_employees") or []:
                    if not isinstance(employee, dict):
                        continue
                    employee_id = str(employee.get("id") or "").strip()
                    if not employee_id:
                        continue
                    profiles[employee_id] = {
                        "name": str(
                            employee.get("label") or employee.get("panel_title") or employee_id
                        ).strip(),
                        "avatar": str(employee.get("market_avatar") or mod_avatar).strip(),
                    }
            return profiles

        self._ai_circle_employee_profiles = _ai_circle_employee_profiles

        def _employee_ssot_payload() -> dict[str, Any]:
            """管理端 6 部门上岗 + 企业端 4 部门上架/未上架，自动派生自 SSOT。"""

            installed: set[str] = set()
            try:
                installed = ports.installed_employee_ids()
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile employee-ssot: 读取已安装 employee_pack 失败: %s", exc)
            return ports.employee_ssot(installed_ids=installed)

        self._employee_ssot_payload = _employee_ssot_payload
