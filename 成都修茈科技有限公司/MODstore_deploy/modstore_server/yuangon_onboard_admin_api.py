"""管理员：yuangon 员工定义与目录上架对齐（状态 / 触发 onboard 脚本）。"""

from __future__ import annotations

import logging
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from fastapi import APIRouter, Body, Depends, HTTPException

from modstore_server.api.deps import require_admin
from modstore_server.integrations.ops_action_handlers import repo_root
from modstore_server.models import CatalogItem, User, get_session_factory
from modstore_server.yuangon_paths import resolve_yuangon_repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-yuangon-onboard"])

DEFAULT_RUNTIME_DIR = str(Path.home() / ".xcmax" / "modstore-daily")
DEFAULT_GOVERNANCE_AUDIT_NAME = "self_maintenance_governance_actions.jsonl"


def _governance_audit_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT")
    if raw:
        return Path(raw)
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or DEFAULT_RUNTIME_DIR) / DEFAULT_GOVERNANCE_AUDIT_NAME


def _append_governance_audit(record: Dict[str, Any]) -> None:
    path = _governance_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        fh.write("\n")


def _yuangon_repo_root() -> Path:
    runtime_roots = [
        os.environ.get("MODSTORE_RUNTIME_ROOT", ""),
        os.environ.get("XCMAX_MONOREPO_ROOT", ""),
    ]
    return resolve_yuangon_repo_root(repo_root(), extra_roots=runtime_roots)


def _parse_onboard_summary(stdout: str) -> Dict[str, int]:
    match = re.search(r"done:\s*onboarded=(\d+),\s*skipped=(\d+),\s*failed=(\d+)", stdout or "", re.I)
    if not match:
        return {}
    return {
        "onboarded": int(match.group(1)),
        "skipped": int(match.group(2)),
        "failed": int(match.group(3)),
    }


def _discover_yuangon_ids(repo: Path) -> tuple[List[str], List[str]]:
    """扫描 ``yuangon/**/employee.yaml`` 返回 (pkg_ids, parse_errors)。"""
    try:
        import yaml
    except ImportError:
        return [], ["PyYAML not installed"]
    repo = resolve_yuangon_repo_root(repo)
    ydir = (repo / "yuangon").resolve()
    if not ydir.is_dir():
        return [], [f"no yuangon directory: {ydir}"]
    ids: Set[str] = set()
    errs: List[str] = []
    for f in sorted(ydir.glob("**/employee.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                pid = str(data.get("id") or "").strip()
                if pid:
                    ids.add(pid)
        except Exception as exc:
            errs.append(f"{f.relative_to(ydir)}: {exc}")
    return sorted(ids), errs


@router.get("/yuangon-onboard/status")
def yuangon_onboard_status(admin_user: User = Depends(require_admin)) -> Dict[str, Any]:
    _ = admin_user
    repo = _yuangon_repo_root()
    yuangon_ids, y_errs = _discover_yuangon_ids(repo)
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(CatalogItem.pkg_id).filter(CatalogItem.artifact == "employee_pack").all()
        )
        catalog_ids = sorted({str(r[0]) for r in rows if r[0]})

    cat_set = set(catalog_ids)
    y_set = set(yuangon_ids)
    missing = sorted(y_set - cat_set)
    extra = sorted(cat_set - y_set)

    return {
        "repo_root": str(repo),
        "yuangon_employee_count": len(yuangon_ids),
        "catalog_employee_pack_count": len(catalog_ids),
        "yuangon_pkg_ids": yuangon_ids,
        "catalog_pkg_ids_sample": catalog_ids[:80],
        "missing_in_catalog": missing,
        "in_catalog_not_in_yuangon_sample": extra[:40],
        "parse_errors": y_errs[:20],
    }


@router.post("/yuangon-onboard/run")
def yuangon_onboard_run(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """执行 ``scripts/onboard_yuangon_employees.py``（子进程，避免长事务阻塞事件循环）。"""
    _ = admin_user
    dry_run = bool(body.get("dry_run", False))
    force = bool(body.get("force", False))
    pkg_raw = str(body.get("pkg_ids") or "").strip()
    repo = _yuangon_repo_root()
    script = Path(__file__).resolve().parent / "scripts" / "onboard_yuangon_employees.py"
    if not script.is_file():
        raise HTTPException(500, f"onboard script missing: {script}")

    cmd: List[str] = [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    if pkg_raw:
        cmd.extend(["--pkg-ids", pkg_raw])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "onboard script timeout (900s)")
    except Exception as exc:
        logger.exception("onboard subprocess failed")
        raise HTTPException(500, str(exc)) from exc

    out = (proc.stdout or "")[-24_000:]
    err = (proc.stderr or "")[-8000:]
    onboard_summary = _parse_onboard_summary(out)
    result = {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": cmd,
        "stdout_tail": out,
        "stderr_tail": err,
        "onboard_summary": onboard_summary,
    }
    audit = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "action": "register_duty_employees",
        "status": "success" if proc.returncode == 0 else "failed",
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "target_employee_ids": [p.strip() for p in pkg_raw.split(",") if p.strip()],
        "dry_run": dry_run,
        "force": force,
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-2000:],
        "onboard_summary": onboard_summary,
        "admin_user_id": getattr(admin_user, "id", None),
        "source": "yuangon_onboard_admin_api",
    }
    try:
        _append_governance_audit(audit)
        result["governance_audit_path"] = str(_governance_audit_path())
    except Exception:
        logger.exception("failed to append governance audit")
        result["governance_audit_error"] = "append_failed"
    return result


__all__ = ["router"]
