# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
        "ruff": {
            "allowed_error_count": 63,
            "allowed_patterns": ["ruff check app", "63 errors"],
        },
        "schema_version": 1,
    }


def load_clean_baseline() -> _facade().Dict[str, _facade().Any]:
    path = _facade().clean_baseline_path()
    if not path.exists():
        return _facade()._default_clean_baseline()
    try:
        data = _facade().json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _facade()._default_clean_baseline()
    except RECOVERABLE_ERRORS:
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


def _read_ledger(
    limit: int = 100,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
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
    row: _facade().Dict[str, _facade().Any],
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
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to read self-maintenance memory")
        return {}


def _read_governance_audit(
    limit: int = 10,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
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


def _append_governance_audit(
    record: _facade().Dict[str, _facade().Any],
) -> _facade().Path:
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
