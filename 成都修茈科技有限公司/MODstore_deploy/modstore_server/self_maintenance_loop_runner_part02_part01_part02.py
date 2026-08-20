# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _governance_audit_summary(
    rows: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    items = rows if isinstance(rows, list) else _facade()._read_governance_audit(10)
    success_count = sum(
        (1 for item in items if isinstance(item, dict) and item.get("ok") is not False)
    )
    failure_count = sum((1 for item in items if isinstance(item, dict) and item.get("ok") is False))
    consecutive_failures = 0
    for item in reversed(items):
        if isinstance(item, dict) and item.get("ok") is False:
            consecutive_failures += 1
        else:
            break
    return {
        "recent_count": len(items),
        "success_count": success_count,
        "failure_count": failure_count,
        "consecutive_failures": consecutive_failures,
        "health": "bad" if consecutive_failures >= 2 else "warn" if failure_count else "ok",
    }


def _governance_audit_gate() -> _facade().Dict[str, _facade().Any]:
    summary = _facade()._governance_audit_summary()
    health = str(summary.get("health") or "").strip()
    ok = health != "bad"
    return {
        "ok": ok,
        "blocking": not ok,
        "action": "allow" if ok else "hold_for_governance_review",
        "reason": "governance_audit_healthy" if ok else "governance_audit_consecutive_failures",
        "summary": summary,
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }


def _policy_active_gates_snapshot(
    *,
    evolution_metrics: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    gate: _facade().Dict[str, _facade().Any],
    governance_gate: _facade().Dict[str, _facade().Any],
    report_only_missing: bool = False,
    roster_gate: _facade().Dict[str, _facade().Any],
    structured_gate: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    evo = evolution_metrics if isinstance(evolution_metrics, dict) else {}
    structured = structured_gate if isinstance(structured_gate, dict) else {"ok": True}
    items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if gate.get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": gate.get("reason") or gate.get("trigger_reason") or "",
            "detail": f"missing={gate.get('missing_count', 0)} threshold={gate.get('threshold', '')}",
        },
        {
            "key": "structured",
            "label": "Structured QA/Review",
            "status": "allow" if structured.get("ok") is not False else "blocked",
            "ok": structured.get("ok") is not False,
            "blocking": structured.get("ok") is False,
            "reason": structured.get("reason") or "",
            "detail": "QA/review JSON gate",
        },
        {
            "key": "report_only",
            "label": "Report-only Evidence",
            "status": "blocked" if report_only_missing else "allow",
            "ok": not report_only_missing,
            "blocking": bool(report_only_missing),
            "reason": "missing_report_only_evidence" if report_only_missing else "",
            "detail": "Para report-only evidence gate",
        },
        {
            "key": "roster",
            "label": "Roster Gate",
            "status": roster_gate.get("action") or "unknown",
            "ok": roster_gate.get("ok") is not False,
            "blocking": bool(roster_gate.get("blocking")),
            "reason": roster_gate.get("reason") or "",
            "detail": roster_gate.get("policy") or "",
        },
        {
            "key": "governance",
            "label": "Governance Gate",
            "status": governance_gate.get("action") or "unknown",
            "ok": governance_gate.get("ok") is not False,
            "blocking": bool(governance_gate.get("blocking")),
            "reason": governance_gate.get("reason") or "",
            "detail": governance_gate.get("policy") or "",
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if evo.get("pause") else "allow",
            "ok": not bool(evo.get("pause")),
            "blocking": bool(evo.get("pause")),
            "reason": evo.get("reason") or "",
            "detail": f"history={evo.get('history_count', 0)}",
        },
    ]
    blocking_items = [item for item in items if item.get("blocking")]
    return {
        "ok": not blocking_items,
        "blocking_count": len(blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in blocking_items],
        "items": items,
    }


def _write_loop_memory(memory: _facade().Dict[str, _facade().Any]) -> None:
    path = _facade().loop_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        _facade().json.dump(memory, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def _memory_context(memory: _facade().Dict[str, _facade().Any]) -> str:
    recent_runs = memory.get("recent_runs") if isinstance(memory, dict) else []
    open_items = memory.get("open_items") if isinstance(memory, dict) else []
    closed_items = memory.get("closed_items") if isinstance(memory, dict) else []
    last_decision = memory.get("last_policy_decision") if isinstance(memory, dict) else None
    payload = {
        "closed_items": closed_items[-8:] if isinstance(closed_items, list) else [],
        "last_policy_decision": last_decision,
        "open_items": open_items[-8:] if isinstance(open_items, list) else [],
        "recent_runs": recent_runs[-5:] if isinstance(recent_runs, list) else [],
    }
    return _facade().json.dumps(payload, ensure_ascii=False, sort_keys=True)[:6000]


def _coerce_str_set(values: _facade().Optional[_facade().List[str]]) -> set:
    return {str(value).strip() for value in values or [] if str(value).strip()}


def _open_item_steps(item: _facade().Dict[str, _facade().Any]) -> _facade().List[str]:
    steps = item.get("steps")
    if not isinstance(steps, list):
        return []
    return [str(step) for step in steps if str(step)]


def _failed_open_item_identity(item: _facade().Dict[str, _facade().Any]) -> str:
    """Stable identity for max-retry open items; run_id alone is not unique enough."""
    return "|".join(
        [
            str(item.get("kind") or ""),
            str(item.get("run_id") or ""),
            str(item.get("branch") or ""),
            str(item.get("para_task_id") or item.get("task_id") or ""),
            ",".join(_facade()._open_item_steps(item)),
            str(item.get("created_at") or ""),
        ]
    )


def _open_item_matches_resolution(
    item: _facade().Dict[str, _facade().Any],
    *,
    branches: set,
    reasons: set,
    run_ids: set,
    task_ids: set,
) -> bool:
    if run_ids and str(item.get("run_id") or "") in run_ids:
        return True
    if branches and str(item.get("branch") or "") in branches:
        return True
    if reasons and str(item.get("reason") or "") in reasons:
        return True
    if task_ids:
        item_task_ids = {
            str(item.get("task_id") or ""),
            str(item.get("para_task_id") or ""),
        }
        if task_ids & {value for value in item_task_ids if value}:
            return True
    return False


def _close_open_items_in_memory(
    memory: _facade().Dict[str, _facade().Any],
    *,
    actor: str,
    branches: _facade().Optional[_facade().List[str]] = None,
    reasons: _facade().Optional[_facade().List[str]] = None,
    resolution_reason: str,
    run_ids: _facade().Optional[_facade().List[str]] = None,
    task_ids: _facade().Optional[_facade().List[str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []
    branch_set = _facade()._coerce_str_set(branches)
    reason_set = _facade()._coerce_str_set(reasons)
    run_id_set = _facade()._coerce_str_set(run_ids)
    task_id_set = _facade()._coerce_str_set(task_ids)
    kept: _facade().List[_facade().Dict[str, _facade().Any]] = []
    closed: _facade().List[_facade().Dict[str, _facade().Any]] = []
    closed_at = _facade()._iso(_facade()._utc_now())
    for item in open_items:
        if not isinstance(item, dict):
            continue
        if _facade()._open_item_matches_resolution(
            item,
            branches=branch_set,
            reasons=reason_set,
            run_ids=run_id_set,
            task_ids=task_id_set,
        ):
            closed.append(
                {
                    "actor": actor,
                    "closed_at": closed_at,
                    "original_item": item,
                    "resolution_reason": resolution_reason,
                }
            )
        else:
            kept.append(item)
    memory["open_items"] = kept[-50:]
    memory["closed_items"] = (closed_items + closed)[-200:]
    memory["updated_at"] = closed_at
    return {"closed_count": len(closed), "closed_items": closed}
