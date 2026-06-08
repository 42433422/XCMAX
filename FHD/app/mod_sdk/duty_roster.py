# -*- coding: utf-8 -*-
"""编制矩阵 ID 加载（与 MODstore duty_roster / AdminDutyEmployeeGraph 对齐）。"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir


def _collect_ids_from_blocks(blocks: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        raw = block.get("ids")
        if isinstance(raw, list):
            ids.extend(str(x).strip() for x in raw if str(x).strip())
        subzones = block.get("subzones")
        if isinstance(subzones, dict):
            ids.extend(_collect_ids_from_blocks(subzones))
    return ids


@lru_cache(maxsize=1)
def load_duty_roster_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg is not None:
        doc = _read_json(cfg / "duty_roster.json")
        if doc and (isinstance(doc.get("areas"), dict) or isinstance(doc.get("departments"), dict)):
            return doc
    return {"schema_version": 1, "areas": {}}


def all_planned_duty_employee_ids() -> frozenset[str]:
    doc = load_duty_roster_document()
    ids: list[str] = []
    areas = doc.get("areas") or {}
    if isinstance(areas, dict):
        ids.extend(_collect_ids_from_blocks(areas))
    if not ids:
        departments = doc.get("departments") or {}
        if isinstance(departments, dict):
            ids.extend(_collect_ids_from_blocks(departments))
    return frozenset(ids)


def load_departments() -> dict[str, Any]:
    doc = load_duty_roster_document()
    departments = doc.get("departments")
    return departments if isinstance(departments, dict) else {}


def primary_department_for_pkg(pkg_id: str) -> str | None:
    """返回 pkg_id 首次出现的部门 five_line_id（编制主归属）。"""
    pid = str(pkg_id or "").strip()
    if not pid:
        return None
    for dept_key, dept in load_departments().items():
        if not isinstance(dept, dict):
            continue
        five_line = str(dept.get("five_line_id") or dept_key)
        subzones = dept.get("subzones") or {}
        if not isinstance(subzones, dict):
            continue
        for block in subzones.values():
            if not isinstance(block, dict):
                continue
            raw = block.get("ids")
            if isinstance(raw, list) and pid in raw:
                return five_line
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except OPERATIONAL_ERRORS:
        return None


__all__ = [
    "load_duty_roster_document",
    "all_planned_duty_employee_ids",
    "load_departments",
    "primary_department_for_pkg",
]
