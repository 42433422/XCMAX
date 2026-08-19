"""Admin autonomy overview aggregation (deploy events, metrics, cross-tier gate)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

UTC = UTC
_FHD_ROOT = Path(__file__).resolve().parents[3]


def _runtime_metrics_dir() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
    if not raw:
        raw = (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _FHD_ROOT / "metrics"


def deploy_events_path() -> Path:
    raw = (os.environ.get("XCAGI_DEPLOY_EVENTS_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _FHD_ROOT / "metrics" / "deploy_events.jsonl"


def autonomy_metrics_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_METRICS_LOG_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _runtime_metrics_dir() / "autonomy-metrics.jsonl"


def _read_jsonl(path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            items.append(row)
        if len(items) >= max(1, limit):
            break
    return items


def list_deploy_events(
    *,
    limit: int = 20,
    since_cursor: str | None = None,
) -> dict[str, Any]:
    """Read deploy_events.jsonl newest-first; optional since_cursor = deploy_id to stop after."""
    bounded = max(1, min(int(limit or 20), 200))
    rows = _read_jsonl(deploy_events_path(), limit=500)
    out: list[dict[str, Any]] = []
    cursor = str(since_cursor or "").strip()
    for row in rows:
        if cursor and str(row.get("deploy_id") or "") == cursor:
            break
        out.append(
            {
                "deploy_id": row.get("deploy_id"),
                "deployed_at": row.get("deployed_at"),
                "commit_at": row.get("commit_at"),
                "status": row.get("status"),
                "restored_at": row.get("restored_at"),
                "source_workflow": row.get("source_workflow"),
                "head_branch": row.get("head_branch"),
            }
        )
        if len(out) >= bounded:
            break
    next_cursor = str(out[-1].get("deploy_id") or "") if out else ""
    return {
        "items": out,
        "count": len(out),
        "next_cursor": next_cursor or None,
        "path": str(deploy_events_path()),
    }


def operating_metrics_windows() -> dict[str, Any]:
    """Return 30d + 90d operating windows (live evaluate + optional jsonl history)."""
    from app.domain.autonomy.operating_metrics import evaluate_autonomy_window

    windows: dict[str, Any] = {}
    for days in (30, 90):
        try:
            report = evaluate_autonomy_window(days)
        except RECOVERABLE_ERRORS as exc:
            report = {"window_days": days, "error": str(exc), "veto_rate": 0.0, "total": 0}
        windows[str(days)] = {
            "window_days": days,
            "veto_rate": float(report.get("veto_rate") or 0.0),
            "action_count": int(report.get("total") or 0),
            "blocked_count": int(
                report.get("veto_count")
                or report.get("blocked_count")
                or (report.get("by_decision") or {}).get("blocked")
                or (report.get("by_decision") or {}).get("BLOCKED")
                or 0
            ),
            "status": report.get("status"),
            "status_reason": report.get("status_reason"),
            "complete": report.get("complete"),
            "observed_days": report.get("observed_days"),
            "by_decision": report.get("by_decision") or {},
        }

    history = _read_jsonl(autonomy_metrics_path(), limit=60)
    trend_30: list[dict[str, Any]] = []
    for row in reversed(history):
        if int(row.get("window_days") or 0) != 30:
            continue
        trend_30.append(
            {
                "snapshot_date": row.get("snapshot_date"),
                "veto_rate": float(row.get("veto_rate") or 0.0),
                "action_count": int(row.get("total") or 0),
            }
        )
    return {
        "windows": windows,
        "veto_rate_trend_30d": trend_30[-30:],
        "metrics_path": str(autonomy_metrics_path()),
    }


def extract_loop_run_summary(runtime: dict[str, Any] | None) -> dict[str, Any]:
    data = runtime if isinstance(runtime, dict) else {}
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    if not isinstance(memory, dict):
        memory = {}
    last_run = memory.get("last_run") if isinstance(memory.get("last_run"), dict) else {}
    timelines = data.get("run_timelines") if isinstance(data.get("run_timelines"), list) else []
    latest_timeline = timelines[0] if timelines and isinstance(timelines[0], dict) else {}
    if not isinstance(last_run, dict):
        last_run = {}
    status = (
        last_run.get("status") or latest_timeline.get("status") or data.get("status") or "unknown"
    )
    run_id = last_run.get("run_id") or latest_timeline.get("run_id")
    return {
        "run_id": run_id,
        "status": status,
        "branch": last_run.get("branch") or latest_timeline.get("branch"),
        "completed_at": last_run.get("completed_at"),
        "triggered_by": last_run.get("triggered_by"),
    }


def closure_gap_count(closure_payload: dict[str, Any] | None) -> int:
    data = closure_payload if isinstance(closure_payload, dict) else {}
    raw_inner = data.get("data")
    inner: dict[str, Any] = dict(raw_inner) if isinstance(raw_inner, dict) else data
    for key in ("gap_count", "closure_gap_count", "open_gap_count"):
        if key in inner:
            try:
                return int(inner.get(key) or 0)
            except (TypeError, ValueError):
                pass
    gaps = inner.get("gaps")
    if isinstance(gaps, list):
        return len(gaps)
    missing = inner.get("missing_remote") or inner.get("missing_local")
    if isinstance(missing, list):
        return len(missing)
    rows = inner.get("roster_rows") or inner.get("rows")
    if isinstance(rows, list):
        return sum(
            1
            for row in rows
            if isinstance(row, dict)
            and (
                row.get("missing_remote")
                or row.get("missing_local")
                or row.get("gap")
                or str(row.get("status") or "").lower() in {"gap", "missing", "缺岗"}
            )
        )
    return 0


def list_github_human_items(*, limit: int = 30) -> dict[str, Any]:
    """Best-effort gh CLI aggregation for ai-self-heal / needs-human labels."""
    bounded = max(1, min(int(limit or 30), 100))
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    cwd = str(_FHD_ROOT.parent if (_FHD_ROOT.parent / ".git").exists() else _FHD_ROOT)

    def _run(args: list[str]) -> list[dict[str, Any]]:
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{' '.join(args[:3])}: {exc}")
            return []
        if proc.returncode != 0:
            errors.append((proc.stderr or proc.stdout or f"exit {proc.returncode}")[:400])
            return []
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            errors.append(f"json: {exc}")
            return []
        return payload if isinstance(payload, list) else []

    prs = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--label",
            "ai-self-heal,needs-human",
            "--limit",
            str(bounded),
            "--json",
            "number,title,url,labels,updatedAt,author,headRefName",
        ]
    )
    for pr in prs:
        items.append(
            {
                "kind": "pr",
                "number": pr.get("number"),
                "title": pr.get("title"),
                "url": pr.get("url"),
                "labels": [
                    str(x.get("name") if isinstance(x, dict) else x)
                    for x in (pr.get("labels") or [])
                ],
                "updated_at": pr.get("updatedAt"),
                "author": (pr.get("author") or {}).get("login")
                if isinstance(pr.get("author"), dict)
                else pr.get("author"),
                "head_ref": pr.get("headRefName"),
            }
        )

    issues = _run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "needs-human",
            "--limit",
            str(bounded),
            "--json",
            "number,title,url,labels,updatedAt,author",
        ]
    )
    for issue in issues:
        items.append(
            {
                "kind": "issue",
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("url"),
                "labels": [
                    str(x.get("name") if isinstance(x, dict) else x)
                    for x in (issue.get("labels") or [])
                ],
                "updated_at": issue.get("updatedAt"),
                "author": (issue.get("author") or {}).get("login")
                if isinstance(issue.get("author"), dict)
                else issue.get("author"),
            }
        )

    items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return {
        "items": items[:bounded],
        "count": min(len(items), bounded),
        "errors": errors,
        "available": not errors or bool(items),
    }


def _load_cross_tier_check():
    path = _FHD_ROOT / "scripts" / "autonomy" / "cross_tier_gate.py"
    mod_name = "xcagi_cross_tier_gate"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load cross_tier_gate script at {path}")
    mod = importlib.util.module_from_spec(spec)
    # dataclasses needs the module registered before exec_module
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except RECOVERABLE_ERRORS:
        sys.modules.pop(mod_name, None)
        raise
    return mod.check_before_action


def evaluate_cross_tier_gate_snapshot(
    remote_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    check_before_action = _load_cross_tier_check()
    state = remote_state if isinstance(remote_state, dict) else _default_remote_state()
    rules = [
        ("desktop", "rollback_version", "桌面回滚 ↔ 服务器 manifest 冻结"),
        ("server", "rollback_to_last_tarball", "服务器回滚 ↔ 桌面 pending marker"),
        ("ci", "cvm-push-release", "CI 推送 ↔ 服务器 manifest 冻结"),
    ]
    results = []
    for tier, action, label in rules:
        gate = check_before_action(tier, action, state)
        results.append(
            {
                "tier": tier,
                "action_type": action,
                "label": label,
                "allow": bool(gate.allow),
                "reasons": list(gate.reasons or []),
            }
        )
    return {"ok": all(r["allow"] for r in results), "rules": results, "remote_state": state}


def _default_remote_state() -> dict[str, Any]:
    """Best-effort local snapshot; missing signals stay false (fail-open rules)."""
    frozen = False
    pending = False
    try:
        for candidate in (
            Path("/opt/fhd-full/.frozen"),
            _FHD_ROOT / ".frozen",
            Path(os.environ.get("XCAGI_FHD_RUNTIME_ROOT") or "") / ".frozen",
        ):
            if candidate and candidate.exists():
                frozen = True
                break
    except OSError:
        pass
    try:
        for candidate in (
            Path.home() / ".xcagi" / "pending-rollback.marker",
            _FHD_ROOT / "desktop" / "autonomy" / "pending-rollback.marker",
        ):
            if candidate.exists():
                pending = True
                break
    except OSError:
        pass
    return {
        "server_manifest_frozen": frozen,
        "desktop_pending_rollback_marker": pending,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def read_cross_tier_audit(
    *,
    tier: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Read audit.jsonl for desktop / server / ci tiers."""
    tier_key = str(tier or "server").strip().lower()
    bounded = max(1, min(int(limit or 50), 300))
    path_map = {
        "desktop": Path.home() / ".xcagi" / "autonomy" / "audit.jsonl",
        "server": Path(
            os.environ.get("XCAGI_AUTONOMY_AUDIT_LOG_PATH") or "/opt/fhd-full/autonomy/audit.jsonl"
        ),
        "ci": _FHD_ROOT / ".trae" / "autonomy-ci" / "audit.jsonl",
    }
    # Prefer local FHD autonomy dir when server path missing (dev)
    server_fallback = _runtime_metrics_dir().parent / "autonomy" / "audit.jsonl"
    if tier_key == "server" and not path_map["server"].is_file() and server_fallback.is_file():
        path_map["server"] = server_fallback
    path = path_map.get(tier_key) or path_map["server"]
    items = _read_jsonl(Path(path), limit=bounded)
    return {
        "tier": tier_key,
        "path": str(path),
        "exists": Path(path).is_file(),
        "items": items,
        "count": len(items),
    }


__all__ = [
    "closure_gap_count",
    "evaluate_cross_tier_gate_snapshot",
    "extract_loop_run_summary",
    "list_deploy_events",
    "list_github_human_items",
    "operating_metrics_windows",
    "read_cross_tier_audit",
]
