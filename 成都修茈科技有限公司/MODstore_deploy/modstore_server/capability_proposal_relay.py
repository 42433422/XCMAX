"""把 FHD 本地能力提案安全中继到 GitHub 治理 issue。

GitHub 定时 runner 看不到桌面运行时的 JSONL。本模块由 MODstore 本地调度器执行，
只调用 FHD 的脱敏/去重脚本，并以 processed 收据验证后置条件。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _repo_root() -> Path | None:
    for name in ("MODSTORE_GIT_REPO_ROOT", "XCMAX_MONOREPO_ROOT"):
        raw = str(os.environ.get(name) or "").strip()
        if raw and Path(raw).is_dir():
            return Path(raw).resolve()
    return None


def _proposal_dirs() -> list[Path]:
    configured = str(os.environ.get("MODSTORE_CAPABILITY_PROPOSAL_DIRS") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item)
    root = _repo_root()
    if root:
        candidates.append(root / "FHD" / "test_reports")
    fhd_root = str(os.environ.get("XCAGI_FHD_ROOT") or "").strip()
    if fhd_root:
        candidates.append(Path(fhd_root) / "test_reports")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path.resolve())
    return unique


def _script_path() -> Path | None:
    root = _repo_root()
    candidates = []
    fhd_root = str(os.environ.get("XCAGI_FHD_ROOT") or "").strip()
    if fhd_root:
        candidates.append(Path(fhd_root) / "scripts" / "dev" / "capability_proposal_to_issue.py")
    if root:
        candidates.append(root / "FHD" / "scripts" / "dev" / "capability_proposal_to_issue.py")
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _parse_repo_slug(remote: str) -> str:
    text = remote.strip()
    match = re.search(r"github\.com[/:]([^/\s]+/[^/\s]+?)(?:\.git)?$", text)
    return match.group(1) if match else ""


def _repo_slug() -> str:
    for name in (
        "MODSTORE_CAPABILITY_PROPOSAL_REPO",
        "GITHUB_REPO",
        "GITHUB_REPOSITORY",
    ):
        value = str(os.environ.get(name) or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            return value
    root = _repo_root()
    if not root:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _parse_repo_slug(result.stdout) if result.returncode == 0 else ""


def _github_token() -> str:
    """Return an in-process GitHub credential without exposing it to argv."""

    for name in ("MODSTORE_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        token = str(os.environ.get(name) or "").strip()
        if token:
            return token
    return ""


def _github_transport(token: str) -> str:
    """Prefer the protected environment credential; CLI is a legacy fallback."""

    if token:
        return "token"
    return "gh_cli" if shutil.which("gh") else ""


def _read_receipts(path: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return receipts
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("dedup_key") or "").strip()
            if key:
                receipts[key] = row
    except OSError:
        logger.warning("capability proposal receipts unreadable: %s", path)
    return receipts


def _pending_count(directory: Path) -> int:
    proposals = directory / "capability_proposal.jsonl"
    processed = set(_read_receipts(directory / "capability_proposal_processed.jsonl"))
    keys: set[str] = set()
    if not proposals.is_file():
        return 0
    try:
        for line in proposals.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("dedup_key") or "").strip()
            if key and key not in processed:
                keys.add(key)
    except OSError:
        return 0
    return len(keys)


def _acquire_lease(directory: Path) -> Path | None:
    lease = directory / "capability_proposal_relay.lock"
    directory.mkdir(parents=True, exist_ok=True)
    stale_seconds = max(60, _env_int("MODSTORE_CAPABILITY_PROPOSAL_LEASE_SECONDS", 600))
    for attempt in range(2):
        try:
            fd = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
            return lease
        except FileExistsError:
            try:
                stale = time.time() - lease.stat().st_mtime > stale_seconds
            except OSError:
                stale = False
            if not stale or attempt:
                return None
            try:
                lease.unlink()
            except OSError:
                return None
    return None


def _append_evolution_event(result: dict[str, Any]) -> None:
    from modstore_server.evolution_ledger import append_event

    append_event(
        {
            "event_type": "capability_proposal_relay_completed",
            "triggered_by": "scheduler",
            "final_status": result.get("status"),
            "created_count": result.get("created_count", 0),
            "reconciled_count": result.get("reconciled_count", 0),
            "ignored_count": result.get("ignored_count", 0),
            "pending_after": result.get("pending_after", 0),
            "issue_urls": result.get("issue_urls", []),
            "postcondition": result.get("postcondition", {}),
            # Configuration errors are stable, non-secret identifiers.  They
            # make an unavailable relay visible to the owner without ever
            # placing credentials or proposal contents in the ledger.
            "configuration_errors": result.get("configuration_errors", []),
            "remediation": result.get("remediation"),
        }
    )


def _configuration_block_has_recent_audit(errors: list[str]) -> bool:
    """Avoid appending the same unresolved configuration block every run."""

    from modstore_server.evolution_ledger import list_events

    expected = sorted(str(item) for item in errors if str(item))
    for event in list_events(
        event_type="capability_proposal_relay_completed",
        final_status="configuration_blocked",
        since_days=1,
    ):
        observed = sorted(
            str(item) for item in (event.get("configuration_errors") or []) if str(item)
        )
        if observed == expected:
            return True
    return False


def _record_configuration_block(result: dict[str, Any]) -> None:
    """Persist a bounded, secret-free audit event for an actionable blocker."""

    errors = [str(item) for item in (result.get("configuration_errors") or []) if str(item)]
    try:
        if _configuration_block_has_recent_audit(errors):
            result["audit_event_written"] = False
            result["audit_event_reason"] = "duplicate_within_24h"
            return
    except Exception:
        # Failure to query the audit ledger must not conceal the original
        # configuration blocker from scheduler health.
        logger.warning("capability proposal relay audit dedupe unavailable", exc_info=True)

    try:
        _append_evolution_event(result)
        result["audit_event_written"] = True
    except Exception:
        # The caller still receives ``configuration_blocked`` and the
        # scheduler records it as a failed job; audit storage is extra
        # evidence, not a reason to rewrite the original failure.
        logger.warning("capability proposal relay audit append failed", exc_info=True)
        result["audit_event_written"] = False
        result["audit_event_reason"] = "append_failed"


def run_capability_proposal_relay() -> dict[str, Any]:
    """扫描本地提案、运行受控中继并验证 processed 收据。"""
    if not _env_bool("MODSTORE_CAPABILITY_PROPOSAL_RELAY_ENABLED", True):
        return {"ok": True, "status": "disabled", "skipped": True}
    directories = [
        path for path in _proposal_dirs() if (path / "capability_proposal.jsonl").is_file()
    ]
    if not directories:
        return {"ok": True, "status": "no_candidates", "scanned_dirs": 0}
    lease = _acquire_lease(directories[0])
    if lease is None:
        return {"ok": True, "status": "lease_busy", "skipped": True}

    script = _script_path()
    repo = _repo_slug()
    result: dict[str, Any] = {
        "ok": True,
        "status": "completed",
        "scanned_dirs": len(directories),
        "created_count": 0,
        "ignored_count": 0,
        "pending_after": 0,
        "issue_urls": [],
        "results": [],
    }
    try:
        token = _github_token()
        transport = _github_transport(token)
        missing: list[str] = []
        if not script:
            missing.append("proposal_relay_script_unavailable")
        if not repo:
            missing.append("proposal_repository_unconfigured")
        if not transport:
            missing.append("github_credentials_unavailable")
        if missing:
            result.update(
                ok=False,
                status="configuration_blocked",
                configuration_errors=missing,
                remediation=(
                    "provision MODSTORE_GITHUB_TOKEN or an authenticated gh client "
                    "through protected runtime configuration"
                ),
            )
            _record_configuration_block(result)
            return result
        max_issues = max(1, _env_int("MODSTORE_CAPABILITY_PROPOSAL_MAX_ISSUES", 5))
        timeout = max(30, _env_int("MODSTORE_CAPABILITY_PROPOSAL_TIMEOUT_SECONDS", 180))
        for directory in directories:
            marker = directory / "capability_proposal_processed.jsonl"
            before = _read_receipts(marker)
            child_env = os.environ.copy()
            child_env["CAPABILITY_PROPOSAL_DIR"] = str(directory)
            command = [
                sys.executable,
                str(script),
                "--repo",
                repo,
                "--max-issues",
                str(max_issues),
            ]
            if transport == "token":
                # capability_proposal_to_issue reads GITHUB_TOKEN from its
                # environment.  Passing it as --token would expose it through
                # process inspection and scheduler diagnostics.
                child_env["GITHUB_TOKEN"] = token
            else:
                command.append("--gh-cli")
            command.append("--apply")
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=child_env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                result["ok"] = False
                result["status"] = "relay_failed"
                result["results"].append({"directory": str(directory), "error": str(exc)[:300]})
                continue
            after = _read_receipts(marker)
            new = [row for key, row in after.items() if key not in before]
            created = [row for row in new if row.get("disposition") == "issue_created"]
            reconciled = [row for row in new if row.get("disposition") == "issue_reconciled"]
            ignored = [row for row in new if row.get("disposition") == "ignored_non_skill_proposal"]
            result["created_count"] += len(created)
            result.setdefault("reconciled_count", 0)
            result["reconciled_count"] += len(reconciled)
            result["ignored_count"] += len(ignored)
            result["issue_urls"].extend(
                str(row.get("issue_url")) for row in [*created, *reconciled] if row.get("issue_url")
            )
            result["pending_after"] += _pending_count(directory)
            result["results"].append(
                {
                    "directory": str(directory),
                    "returncode": completed.returncode,
                    "new_receipts": len(new),
                }
            )
            if completed.returncode != 0:
                result["ok"] = False
                result["status"] = "relay_failed"
        result["postcondition"] = {
            "processed_receipts_written": result["created_count"] + result["ignored_count"],
            "reconciled_receipts_written": result.get("reconciled_count", 0),
            "pending_recounted": True,
        }
        if (
            result["created_count"]
            or result.get("reconciled_count", 0)
            or result["ignored_count"]
            or not result["ok"]
        ):
            _append_evolution_event(result)
        return result
    finally:
        try:
            lease.unlink()
        except OSError:
            logger.warning("capability proposal relay lease cleanup failed: %s", lease)


def register_capability_proposal_relay_job(
    scheduler: Any,
    *,
    track_job: Callable[[str, Callable[[], Any]], Any],
) -> None:
    """注册本地中继任务，保持巨型 workflow_scheduler 只负责接线。"""
    from apscheduler.triggers.interval import IntervalTrigger

    def _job() -> None:
        try:

            def _run() -> dict[str, Any]:
                result = run_capability_proposal_relay()
                if result.get("ok") is not True:
                    raise RuntimeError(f"capability_proposal_relay_failed:{result.get('status')}")
                return result

            result = track_job("capability_proposal_relay", _run)
            logger.info(
                "capability proposal relay: status=%s created=%s ignored=%s pending=%s",
                result.get("status"),
                result.get("created_count", 0),
                result.get("ignored_count", 0),
                result.get("pending_after", 0),
            )
        except Exception:
            logger.exception("capability proposal relay failed")

    interval = max(
        10,
        _env_int("MODSTORE_CAPABILITY_PROPOSAL_RELAY_INTERVAL_MINUTES", 30),
    )
    scheduler.add_job(
        _job,
        IntervalTrigger(minutes=interval),
        id="capability_proposal_relay",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=35),
        misfire_grace_time=max(
            60,
            _env_int("MODSTORE_SCHEDULER_BUSINESS_MISFIRE_GRACE_SECONDS", 3600),
        ),
        coalesce=True,
        max_instances=1,
    )


__all__ = ["register_capability_proposal_relay_job", "run_capability_proposal_relay"]
