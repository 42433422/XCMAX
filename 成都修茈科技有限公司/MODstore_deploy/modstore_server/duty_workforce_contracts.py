"""Runtime loader for the 55-role duty workforce work contracts.

The roster says who exists.  This file loads the separate contract SSOT that
says what each employee is expected to do, how work is triggered, how risky it
is, and what evidence counts as a receipt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _candidate_paths() -> Iterable[Path]:
    configured = str(os.environ.get("MODSTORE_DUTY_WORK_CONTRACTS_PATH") or "").strip()
    if configured:
        yield Path(configured).expanduser()
    monorepo = str(os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if monorepo:
        yield Path(monorepo).expanduser() / "FHD" / "config" / "duty_employee_work_contracts.json"
    # Source checkout contains an extra company-site directory while the local
    # autonomy runtime mounts MODstore_deploy directly under its runtime root.
    # Search ancestors instead of baking in either layout.
    for parent in Path(__file__).resolve().parents:
        yield parent / "FHD" / "config" / "duty_employee_work_contracts.json"


def resolve_work_contracts_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate.resolve()
    return next(iter(_candidate_paths())).resolve()


def load_workforce_contracts(path: Optional[Path] = None) -> Dict[str, Any]:
    target = resolve_work_contracts_path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"duty work contracts unavailable: {target}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"duty work contracts invalid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("duty work contracts root must be an object")
    rows = payload.get("contracts")
    if not isinstance(rows, list):
        raise RuntimeError("duty work contracts must contain contracts[]")
    seen: set[str] = set()
    normalized: list[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise RuntimeError("duty work contract rows must be objects")
        employee_id = str(raw.get("employee_id") or "").strip()
        if not employee_id:
            raise RuntimeError("duty work contract missing employee_id")
        if employee_id in seen:
            raise RuntimeError(f"duplicate duty work contract: {employee_id}")
        seen.add(employee_id)
        trigger = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
        if not str(trigger.get("cron") or "").strip() and not trigger.get("events"):
            raise RuntimeError(f"duty work contract has no trigger: {employee_id}")
        normalized.append({**raw, "employee_id": employee_id, "trigger": trigger})
    return {**payload, "path": str(target), "contracts": normalized}


def workforce_contract_map(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    payload = load_workforce_contracts(path)
    return {str(row["employee_id"]): row for row in payload["contracts"]}


def _duty_manifest_roots() -> Iterable[Path]:
    configured = str(os.environ.get("MODSTORE_DUTY_EMPLOYEE_MANIFEST_ROOT") or "").strip()
    if configured:
        yield Path(configured).expanduser()
    monorepo = str(os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if monorepo:
        yield Path(monorepo).expanduser() / "FHD" / "mods" / "_employees"
    try:
        fhd_root = resolve_work_contracts_path().parent.parent
        yield fhd_root / "mods" / "_employees"
    except Exception:
        pass


def resolve_reviewed_duty_employee_root(employee_id: str) -> Path:
    """Resolve one duty employee directory from the reviewed runtime SSOT.

    Burn-in must execute the Python module shipped beside the exact manifest it
    reviewed. Returning a catalog ZIP here would allow a stale package body to
    run under a newer source contract.
    """

    eid = str(employee_id or "").strip()
    if not eid or Path(eid).name != eid or eid not in workforce_contract_map():
        raise RuntimeError(f"employee is not in reviewed duty contracts: {eid or '?'}")
    checked: list[str] = []
    for raw_root in _duty_manifest_roots():
        root = raw_root.expanduser().resolve()
        target = (root / eid).resolve()
        checked.append(str(target / "manifest.json"))
        try:
            target.relative_to(root)
            payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("id") or "").strip() != eid:
            continue
        if not isinstance(payload.get("employee_config_v2"), dict):
            continue
        return target
    raise RuntimeError(f"reviewed duty manifest unavailable: {eid}; checked={checked}")


def load_reviewed_duty_manifest(employee_id: str) -> Dict[str, Any]:
    """Load the reviewed FHD manifest SSOT for one contracted duty employee.

    Catalog archives can legitimately lag source deployment.  Burn-in must not
    prove an old generic shell after the reviewed duty manifest gained a real
    handler.  This loader is intentionally explicit and is only consumed by
    the read-only burn-in path; normal customer executions retain catalog
    package authority.
    """

    root = resolve_reviewed_duty_employee_root(employee_id)
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def contract_schedule(contract: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a cron work contract to the existing employee scheduler shape."""

    trigger = contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
    cron_expr = str(trigger.get("cron") or "").strip()
    if not cron_expr:
        return None
    mission = str(contract.get("mission") or "").strip()
    mode = str(contract.get("mode") or "execute").strip()
    risk = str(contract.get("risk_level") or "medium").strip()
    acceptance = [
        str(item).strip() for item in contract.get("acceptance") or [] if str(item).strip()
    ]
    task_brief = (
        f"岗位任务：{mission}\n"
        f"执行模式：{mode}；风险级别：{risk}。\n"
        f"验收回执：{'；'.join(acceptance) or '写入员工执行指标并保留结果摘要'}。\n"
        "必须使用真实输入与工具结果；缺少数据时明确标记，不得用回显或虚构数据冒充完成。"
    )
    return {
        "enabled": True,
        "cron": cron_expr,
        "task_brief": task_brief,
        "source": "duty_work_contract",
        "mode": mode,
        "risk_level": risk,
    }


def workforce_event_bindings(path: Optional[Path] = None) -> list[Dict[str, Any]]:
    """Return event-driven assignments, including optional ``event:source`` filters."""

    out: list[Dict[str, Any]] = []
    for employee_id, contract in workforce_contract_map(path).items():
        trigger = contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
        for raw in trigger.get("events") or []:
            event_type = str(raw or "").strip()
            if not event_type:
                continue
            out.append(
                {
                    "employee_id": employee_id,
                    "event_type": event_type,
                    "mission": str(contract.get("mission") or ""),
                    "mode": str(contract.get("mode") or "event"),
                    "risk_level": str(contract.get("risk_level") or "medium"),
                    "acceptance": list(contract.get("acceptance") or []),
                }
            )
    return out


__all__ = [
    "contract_schedule",
    "load_workforce_contracts",
    "load_reviewed_duty_manifest",
    "resolve_reviewed_duty_employee_root",
    "resolve_work_contracts_path",
    "workforce_contract_map",
    "workforce_event_bindings",
]
