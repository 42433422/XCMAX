# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _utc_now() -> _facade().datetime:
    return _facade().datetime.now(_facade().timezone.utc)


def _iso(dt: _facade().datetime) -> str:
    return dt.astimezone(_facade().timezone.utc).isoformat()


def _env_int(name: str, default: int) -> int:
    raw = _facade().os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        _facade().logger.warning("invalid integer env %s=%r; using %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _facade().os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_flag_enabled(name: str) -> bool:
    """Master switches that default OFF when unset (dry-run 等显式危险开关)。"""
    return _facade()._env_bool(name, False)


def _auto_dispatch_deploy_enabled() -> bool:
    """staging 自动部署主开关：未设置时默认开启；显式 0/false/off 关闭。"""
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY")
    if raw is None or not str(raw).strip():
        return True
    return _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY", True)


def _env_list(name: str, default: _facade().List[str]) -> _facade().List[str]:
    raw = _facade().os.environ.get(name)
    if raw is None or not str(raw).strip():
        return list(default)
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    return values or list(default)


def _runtime_dir() -> _facade().Path:
    return _facade().Path(
        _facade().os.environ.get("MODSTORE_RUNTIME_DIR") or _facade().DEFAULT_RUNTIME_DIR
    )


def ledger_path() -> _facade().Path:
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER")
    return _facade().Path(raw) if raw else _facade()._runtime_dir() / _facade().DEFAULT_LEDGER_NAME


def loop_memory_path() -> _facade().Path:
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY")
    return _facade().Path(raw) if raw else _facade()._runtime_dir() / _facade().DEFAULT_MEMORY_NAME


def governance_audit_path() -> _facade().Path:
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT")
    return (
        _facade().Path(raw)
        if raw
        else _facade()._runtime_dir() / _facade().DEFAULT_GOVERNANCE_AUDIT_NAME
    )


def clean_baseline_path() -> _facade().Path:
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE")
    if raw:
        return _facade().Path(raw)
    kb_root = _facade().os.environ.get("XCMAX_SELF_EVOLUTION_KB_ROOT") or _facade().os.environ.get(
        "XCMAX_KB_ROOT"
    )
    if kb_root:
        return (
            _facade().Path(kb_root).expanduser() / "metrics" / _facade().DEFAULT_CLEAN_BASELINE_NAME
        )
    return _facade()._runtime_dir() / _facade().DEFAULT_CLEAN_BASELINE_NAME


def _default_clean_baseline() -> _facade().Dict[str, _facade().Any]:
    return {
        "baseline_id": "initial-current-known-failures-2026-06-18",
        "created_at": "2026-06-18T23:37:10+00:00",
        "notes": "Initial clean baseline from the first real report-only QA pass. QA must fail only for new failures beyond this baseline and should refresh allowed_failure_nodeids when a clean full-test collection is available.",
        "openapi": {
            "allowed_error_count": 0,
            "allowed_info_count": 49,
            "allowed_warn_count": 1819,
            "allowed_patterns": ["routes=1076 ops=1028", "warn=1819", "info=49"],
        },
        "pytest": {
            "allowed_error_count": 32,
            "allowed_failure_count": 80,
            "allowed_error_nodeids": [],
            "allowed_failure_nodeids": [],
            "allowed_failure_patterns": [
                "PermissionError",
                "sidebar_menu_manager.py",
                "outside this workspace",
            ],
            "source_run_id": "84c3aaf5-d3ff-420f-a31b-4680451cebbd",
        },
        "ruff": {"allowed_error_count": 63, "allowed_patterns": ["ruff check app", "63 errors"]},
        "schema_version": 1,
    }


def load_clean_baseline() -> _facade().Dict[str, _facade().Any]:
    path = _facade().clean_baseline_path()
    if not path.exists():
        return _facade()._default_clean_baseline()
    try:
        data = _facade().json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _facade()._default_clean_baseline()
    except Exception:
        _facade().logger.exception("failed to read clean baseline")
        return _facade()._default_clean_baseline()


def ensure_clean_baseline() -> _facade().Dict[str, _facade().Any]:
    path = _facade().clean_baseline_path()
    if path.exists():
        return _facade().load_clean_baseline()
    baseline = _facade()._default_clean_baseline()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        _facade().json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return baseline


def _clean_baseline_context() -> str:
    return _facade().json.dumps(
        _facade().load_clean_baseline(), ensure_ascii=False, sort_keys=True
    )[:4000]


def _append_ledger(record: _facade().Dict[str, _facade().Any]) -> None:
    record = dict(record)
    run_id = str(record.get("run_id") or "").strip()
    if run_id:
        record.setdefault("correlation_id", run_id)
    record.setdefault("ledger_schema_version", 2)
    path = _facade().ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(_facade().json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_ledger(limit: int = 100) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    path = _facade().ledger_path()
    if not path.exists():
        return []
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(_facade().json.loads(line))
                except _facade().json.JSONDecodeError:
                    continue
    except OSError:
        _facade().logger.exception("failed to read self-maintenance ledger")
        return []
    return rows[-limit:]


def _ledger_row_timestamp(
    row: _facade().Dict[str, _facade().Any]
) -> _facade().Optional[_facade().datetime]:
    """Return a normalized timestamp for one append-only ledger row.

    Step records use ``timestamp`` while start/terminal records use one of the
    ``*_at`` fields.  Keeping that compatibility here prevents an otherwise
    valid step from becoming timeless when it is projected into runtime
    evidence.
    """
    for key in (
        "timestamp",
        "created_at",
        "completed_at",
        "updated_at",
        "started_at",
        "verified_at",
        "deployed_at",
        "at",
    ):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = _facade().datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_facade().timezone.utc)
        return parsed.astimezone(_facade().timezone.utc)
    return None


def _select_recent_milestone_rows(
    rows: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    now: _facade().Optional[_facade().datetime] = None,
    window_days: int = _facade().DEFAULT_EVIDENCE_WINDOW_DAYS,
    run_limit: int = _facade().DEFAULT_EVIDENCE_RUN_LIMIT,
    row_limit: int = _facade().DEFAULT_EVIDENCE_ROW_LIMIT,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """Select coherent, time-bounded work evidence immune to heartbeat churn.

    The live feed remains intentionally small, but proof of a recent completed
    work cycle must not disappear merely because the scheduler emitted many
    idle heartbeats or policy skips.  Rows without a parseable timestamp are
    excluded, and evidence expires after ``window_days`` so an old success can
    never prove current autonomy forever.
    """
    current = (now or _facade()._utc_now()).astimezone(_facade().timezone.utc)
    bounded_days = max(1, min(int(window_days or _facade().DEFAULT_EVIDENCE_WINDOW_DAYS), 90))
    bounded_runs = max(1, min(int(run_limit or _facade().DEFAULT_EVIDENCE_RUN_LIMIT), 64))
    bounded_rows = max(1, min(int(row_limit or _facade().DEFAULT_EVIDENCE_ROW_LIMIT), 512))
    cutoff = current - _facade().timedelta(days=bounded_days)
    future_tolerance = current + _facade().timedelta(minutes=5)
    excluded_phases = {"heartbeat", "skip", "kb_salvage"}
    eligible: _facade().List[
        _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().datetime]
    ] = []
    latest_by_run: _facade().Dict[str, _facade().datetime] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        phase = str(row.get("phase") or "").strip().lower()
        if phase in excluded_phases:
            continue
        if not phase and (not row.get("event")) and (not row.get("event_type")):
            continue
        observed_at = _facade()._ledger_row_timestamp(row)
        if observed_at is None or observed_at < cutoff or observed_at > future_tolerance:
            continue
        eligible.append((row, observed_at))
        run_id = str(row.get("run_id") or "").strip()
        if run_id and observed_at > latest_by_run.get(run_id, cutoff):
            latest_by_run[run_id] = observed_at
    selected_run_ids = {
        run_id
        for (run_id, _) in sorted(latest_by_run.items(), key=lambda item: item[1])[-bounded_runs:]
    }
    return _facade().retain_completed_merge_runs(
        eligible,
        latest_by_run=latest_by_run,
        recent_run_ids=selected_run_ids,
        cutoff=cutoff,
        row_limit=bounded_rows,
    )


def loop_lease_path() -> _facade().Path:
    raw = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_LEASE_FILE")
    return (
        _facade().Path(raw) if raw else _facade()._runtime_dir() / _facade().DEFAULT_LOOP_LEASE_NAME
    )


@_facade().contextmanager
def _exclusive_loop_lease():
    """Hold one OS-backed lease for the complete maintenance transaction."""
    path = _facade().loop_lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError):
            acquired = False
        if acquired:
            fh.seek(0)
            fh.truncate()
            fh.write(
                _facade().json.dumps(
                    {
                        "acquired_at": _facade()._iso(_facade()._utc_now()),
                        "hostname": _facade().socket.gethostname(),
                        "pid": _facade().os.getpid(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            fh.flush()
        yield acquired
    finally:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        fh.close()


def _load_loop_memory() -> _facade().Dict[str, _facade().Any]:
    path = _facade().loop_memory_path()
    if not path.exists():
        return {
            "closed_items": [],
            "open_items": [],
            "recent_runs": [],
            "run_count": 0,
            "updated_at": None,
        }
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = _facade().json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        _facade().logger.exception("failed to read self-maintenance memory")
        return {}


def _read_governance_audit(limit: int = 10) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    path = _facade().governance_audit_path()
    if not path.exists():
        return []
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = _facade().json.loads(line)
                except _facade().json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        _facade().logger.exception("failed to read self-maintenance governance audit")
        return []
    return rows[-limit:]


def _append_governance_audit(record: _facade().Dict[str, _facade().Any]) -> _facade().Path:
    path = _facade().governance_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(_facade().json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def record_governance_audit_review(
    *, note: str = "", admin_user_id: _facade().Optional[_facade().Any] = None
) -> _facade().Dict[str, _facade().Any]:
    recent = _facade()._read_governance_audit(10)
    summary = _facade()._governance_audit_summary(recent)
    record = {
        "action": "review_governance_audit",
        "admin_user_id": admin_user_id,
        "created_at": _facade()._iso(_facade()._utc_now()),
        "note": str(note or "")[:1000],
        "ok": True,
        "previous_summary": summary,
        "source": "self_maintenance_loop_api",
        "status": "reviewed",
    }
    path = _facade()._append_governance_audit(record)
    next_recent = _facade()._read_governance_audit(10)
    return {
        "ok": True,
        "audit_path": str(path),
        "record": record,
        "summary": _facade()._governance_audit_summary(next_recent),
    }


def _governance_audit_summary(
    rows: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None
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
        item_task_ids = {str(item.get("task_id") or ""), str(item.get("para_task_id") or "")}
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
            item, branches=branch_set, reasons=reason_set, run_ids=run_id_set, task_ids=task_id_set
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


def close_loop_memory_items(
    *,
    actor: str = "self_maintenance",
    branches: _facade().Optional[_facade().List[str]] = None,
    reasons: _facade().Optional[_facade().List[str]] = None,
    resolution_reason: str,
    run_ids: _facade().Optional[_facade().List[str]] = None,
    task_ids: _facade().Optional[_facade().List[str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Close resolved loop-memory risks without deleting audit history."""
    memory = _facade()._load_loop_memory()
    result = _facade()._close_open_items_in_memory(
        memory,
        actor=actor,
        branches=branches,
        reasons=reasons,
        resolution_reason=resolution_reason,
        run_ids=run_ids,
        task_ids=task_ids,
    )
    _facade()._write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(_facade().loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }
