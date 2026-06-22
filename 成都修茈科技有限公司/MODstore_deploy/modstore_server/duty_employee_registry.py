"""Dedicated registry for management-side duty employees.

Public/store employee packs live in ``catalog_data/packages.json``.
Duty employees are internal management staff and must not be treated as store
items, even when their runtime package files still live under catalog_data/files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.duty_roster import (
    employee_partition_meta,
    is_planned_duty_employee_pack,
)


def duty_registry_path() -> Path:
    from modstore_server.catalog_store import packages_path

    return packages_path().with_name("duty_employee_registry.json")


def load_duty_registry() -> Dict[str, Any]:
    path = duty_registry_path()
    if not path.is_file():
        return {"schema": 1, "packages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": 1, "packages": []}
    if not isinstance(data, dict):
        return {"schema": 1, "packages": []}
    packages = data.get("packages")
    if not isinstance(packages, list):
        data["packages"] = []
    return data


def save_duty_registry(data: Dict[str, Any]) -> None:
    path = duty_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload.setdefault("schema", 1)
    payload.setdefault("packages", [])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record_pkg_id(record: Dict[str, Any]) -> str:
    return str(record.get("id") or record.get("pkg_id") or "").strip()


def duty_employee_records() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in load_duty_registry().get("packages") or []:
        if not isinstance(raw, dict):
            continue
        pid = _record_pkg_id(raw)
        if not is_planned_duty_employee_pack(pid, str(raw.get("artifact") or "employee_pack")):
            continue
        rec = dict(raw)
        rec.update(employee_partition_meta(pid, "employee_pack"))
        rec["is_public"] = False
        rec["market_visible"] = False
        out[pid] = rec
    return out


def get_duty_employee_record(pack_id: str) -> Optional[Dict[str, Any]]:
    return duty_employee_records().get(str(pack_id or "").strip())


def list_duty_employee_records() -> List[Dict[str, Any]]:
    return [duty_employee_records()[k] for k in sorted(duty_employee_records())]

