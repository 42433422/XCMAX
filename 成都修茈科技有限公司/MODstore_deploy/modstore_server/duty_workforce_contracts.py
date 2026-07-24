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


def matching_duty_event_contract(
    employee_id: str,
    event_type: str,
    source: str = "",
    *,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return a safe reviewed contract for one concrete event dispatch.

    A source-qualified subscription such as ``employee.task.done:intent-analyst``
    matches only that source.  High-risk contracts intentionally never become
    unattended event work; they continue through approval/veto and release
    verification paths.
    """

    contract = workforce_contract_map(path).get(str(employee_id or "").strip()) or {}
    if str(contract.get("risk_level") or "").strip().lower() not in {"low", "medium"}:
        return {}
    trigger = contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
    declared = {str(item or "").strip() for item in trigger.get("events") or []}
    event_key = str(event_type or "").strip()
    source_key = str(source or "").strip()
    if event_key in declared or (source_key and f"{event_key}:{source_key}" in declared):
        return dict(contract)
    return {}


def enrich_customer_ticket_publish_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize publish-boundary payload for ``ops.intake.customer_ticket``.

    Guarantees ``requests`` / ``ticket`` shapes before the event hits incident_bus
    bindings, so no consumer depends on a later enrich path that might be skipped.
    """

    body = dict(payload or {})
    _enrich_customer_ticket_duty_input("intake-dispatcher", body, body)
    _enrich_customer_ticket_duty_input("user-customer-service-officer", body, body)
    return body


def _enrich_customer_ticket_duty_input(
    employee_id: str,
    payload: Dict[str, Any],
    incident: Dict[str, Any],
) -> None:
    """Map incident-bus fields into deterministic direct_python shapes.

    Reviewed duty packs for intake / CS expect ``requests`` / ``ticket``. Raw
    ``ops.intake.customer_ticket`` payloads only carry ticket_id/summary, which
    previously made every binding dispatch ``handler_failed``.
    """

    eid = str(employee_id or "").strip()
    ticket_no = str(
        incident.get("ticket_no") or incident.get("subject_id") or incident.get("ticket_id") or ""
    ).strip()
    summary = str(incident.get("summary") or incident.get("title") or "").strip()
    raw = incident.get("raw") if isinstance(incident.get("raw"), dict) else {}
    if not summary:
        summary = str(raw.get("body") or raw.get("title") or "").strip()
    if eid == "intake-dispatcher" and not (
        isinstance(payload.get("requests"), list) and payload.get("requests")
    ):
        text = summary or f"客服工单 {ticket_no or '?'} 待归一化"
        payload["requests"] = [
            {
                "id": ticket_no or "customer-ticket",
                "text": text[:2000],
                "route_hint": "user-customer-service-officer",
            }
        ]
    if eid == "user-customer-service-officer" and not isinstance(payload.get("ticket"), dict):
        payload["ticket"] = {
            "id": ticket_no or "CS-unknown",
            "issue": summary or f"客服工单 {ticket_no or '?'}",
            "knowledge_sources": [
                {
                    "source": "customer_ticket_incident",
                    "text": (summary or ticket_no or "customer_ticket")[:500],
                }
            ],
            "severity": str(incident.get("severity") or "normal").strip().lower() or "normal",
        }
    # surface common fields for modules that read top-level keys
    if ticket_no and not payload.get("ticket_no"):
        payload["ticket_no"] = ticket_no
    if summary and not payload.get("summary"):
        payload["summary"] = summary


def duty_event_execution_input(
    employee_id: str,
    *,
    event_type: str,
    source: str,
    incident: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build fail-closed executor input for a reviewed low/medium event duty."""

    contract = matching_duty_event_contract(employee_id, event_type, source)
    if not contract:
        return {}
    project_root = str(
        os.environ.get("MODSTORE_DUTY_PROJECT_ROOT") or os.environ.get("XCMAX_MONOREPO_ROOT") or ""
    ).strip()
    incident_body = dict(incident or {})
    payload: Dict[str, Any] = {
        "allow_high_risk_real_run": False,
        "allow_medium_risk": True,
        "event_type": str(event_type or "").strip(),
        "incident": incident_body,
        "non_blocking_human_questions": True,
        "schedule_source": "duty_work_contract",
        "source": str(source or "").strip(),
        "suppress_lifecycle_events": True,
        "trigger": "event",
        "unified_incident_bus": True,
        "work_contract": {
            "schema": "xcagi.duty_employee_work_contracts/v1",
            "mode": str(contract.get("mode") or "event"),
            "risk_level": str(contract.get("risk_level") or "medium"),
            "acceptance": list(contract.get("acceptance") or []),
        },
    }
    if project_root:
        payload["project_root"] = project_root
    if str(event_type or "").strip() == "ops.intake.customer_ticket" or str(
        incident_body.get("source") or ""
    ).strip().lower() in {"customer_ticket", "customer-service-api", "customer-service-sim"}:
        _enrich_customer_ticket_duty_input(employee_id, payload, incident_body)
    return payload


__all__ = [
    "contract_schedule",
    "duty_event_execution_input",
    "enrich_customer_ticket_publish_payload",
    "load_workforce_contracts",
    "load_reviewed_duty_manifest",
    "matching_duty_event_contract",
    "resolve_reviewed_duty_employee_root",
    "resolve_work_contracts_path",
    "workforce_contract_map",
    "workforce_event_bindings",
]
