"""自动审批策略：评估 ChangeRequest 风险级别，低风险自动落盘。

环境变量：
  MODSTORE_AUTO_APPROVE_ENABLED      = "1" 启用自动审批（默认关闭）
  MODSTORE_AUTO_APPROVE_MAX_LINES    = "50" 自动审批最大变更行数阈值
  MODSTORE_AUTO_APPROVE_REQUIRE_CI   = "1" 是否要求 CI 通过后才自动审批（默认 "0"）
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 配置读取
# --------------------------------------------------------------------------- #


def _auto_approve_enabled() -> bool:
    return os.environ.get("MODSTORE_AUTO_APPROVE_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _max_lines() -> int:
    try:
        return int(os.environ.get("MODSTORE_AUTO_APPROVE_MAX_LINES", "50"))
    except ValueError:
        return 50


def _require_ci() -> bool:
    return os.environ.get("MODSTORE_AUTO_APPROVE_REQUIRE_CI", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# --------------------------------------------------------------------------- #
# 风险评估
# --------------------------------------------------------------------------- #

# 高风险文件类型（含机密/配置/数据库/密钥相关）
_HIGH_RISK_SUFFIXES = frozenset(
    {
        ".env",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".db",
        ".sqlite",
        ".sqlite3",
    }
)

_HIGH_RISK_PATTERNS = [
    "*.env",
    "*.env.*",
    "secrets/*",
    ".github/workflows/*",
    "nginx/*.conf",
    "*/nginx.conf",
    "requirements*.txt",
    "Dockerfile*",
    "docker-compose*.yml",
    "modstore_server/models*.py",
    "modstore_server/api/app_factory.py",
]


def _path_matches_any(rel_path: str, patterns: Sequence[str]) -> bool:
    rp = rel_path.replace("\\", "/").lower()
    for pat in patterns or []:
        p = str(pat or "").strip().lower()
        if not p:
            continue
        if fnmatch.fnmatch(rp, p) or fnmatch.fnmatch(rp, ("**/" + p).lower()):
            return True
    return False


def _path_is_high_risk(rel_path: str, forbidden_globs: Sequence[str] = ()) -> bool:
    """检查路径是否属于内置高风险或 forbidden_globs。"""
    # forbidden_globs 命中 → 必须人工审批
    rp = rel_path.replace("\\", "/").lower()
    if _path_matches_any(rp, forbidden_globs):
        return True
    # 内置高风险
    for suffix in _HIGH_RISK_SUFFIXES:
        if rp.endswith(suffix):
            return True
    for pat in _HIGH_RISK_PATTERNS:
        if fnmatch.fnmatch(rp, pat.lower()):
            return True
    return False


def _path_requires_manual_approval(
    rel_path: str, approval_required_globs: Sequence[str] = ()
) -> bool:
    """命中 ``approval_required_globs`` 时，强制走人工/邮件审批，不可自动批准。"""
    return _path_matches_any(rel_path, approval_required_globs)


def _count_diff_lines(content: str, original: Optional[str] = None) -> int:
    """简单行数统计：若无 original，统计 content 行数。"""
    if original is not None:
        orig_lines = set(original.splitlines())
        new_lines = content.splitlines()
        changed = sum(1 for ln in new_lines if ln not in orig_lines)
        return changed
    return len((content or "").splitlines())


def evaluate_risk(
    rel_path: str,
    content: str,
    *,
    scope_globs: Sequence[str] = (),
    forbidden_globs: Sequence[str] = (),
    approval_required_globs: Sequence[str] = (),
    original_content: Optional[str] = None,
) -> Tuple[str, str]:
    """返回 (risk_level, reason)。

    risk_level: "low" | "medium" | "high"
    """
    if _path_is_high_risk(rel_path, forbidden_globs):
        return "high", f"路径 {rel_path} 命中高风险规则或 forbidden_globs"
    if _path_requires_manual_approval(rel_path, approval_required_globs):
        return "medium", f"路径 {rel_path} 命中 approval_required_globs，强制人工审批"
    try:
        from modstore_server.self_maintenance_policy import (
            is_marker_status_path,
            loop_memory_requires_executable_change,
        )

        if is_marker_status_path(rel_path):
            requirement = loop_memory_requires_executable_change()
            if requirement.get("required"):
                return (
                    "medium",
                    "self-maintenance marker-only change requires human review: "
                    + str(requirement.get("reason") or ""),
                )
    except Exception:
        return "medium", "self-maintenance policy check failed closed"

    line_count = _count_diff_lines(content, original_content)
    max_l = _max_lines()

    if line_count > max_l * 4:
        return "high", f"变更行数 {line_count} 超过高风险阈值 {max_l * 4}"

    if scope_globs:
        import fnmatch as _fnmatch

        rp = rel_path.replace("\\", "/")
        matched = any(_fnmatch.fnmatch(rp, g) for g in scope_globs)
        if not matched:
            return "medium", f"路径 {rel_path} 不在 scope_globs 范围内"

    if line_count > max_l:
        return "medium", f"变更行数 {line_count} 超过自动审批阈值 {max_l}"

    return "low", f"变更行数 {line_count} ≤ {max_l}，路径在 scope 内"


# --------------------------------------------------------------------------- #
# 自动审批入口
# --------------------------------------------------------------------------- #


def maybe_auto_approve(change_request_id: int) -> Dict[str, Any]:
    """检查并尝试自动审批。

    返回 {"auto_approved": bool, "reason": str, "result": ...}
    """
    if not _auto_approve_enabled():
        return {
            "auto_approved": False,
            "reason": "auto_approve disabled (MODSTORE_AUTO_APPROVE_ENABLED)",
        }

    try:
        from modstore_server.employee_runtime import load_employee_pack
        from modstore_server.employee_scope_policy import workspace_policy_from_manifest
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(EmployeeChangeRequest, int(change_request_id))
            if not row:
                return {"auto_approved": False, "reason": "change_request not found"}
            if (row.status or "") != "pending":
                return {"auto_approved": False, "reason": f"status={row.status}"}

            try:
                data = json.loads(row.diff_blob or "{}")
            except json.JSONDecodeError:
                return {"auto_approved": False, "reason": "invalid diff_blob"}

            rel_path = str(data.get("path") or "").strip()
            content = str(data.get("content") or "")
            source_employee_id = str(row.source_employee_id or "")
            risk = str(row.risk_level or "medium")
            try:
                ag_from_row = [
                    str(x).strip()
                    for x in json.loads(getattr(row, "approval_required_globs_json", "[]") or "[]")
                    if str(x).strip()
                ]
            except Exception:
                ag_from_row = []
            ag_snapshot = [
                str(x).strip()
                for x in (data.get("approval_required_globs_snapshot") or [])
                if str(x).strip()
            ]

            # 尝试读取员工 scope 策略
            try:
                pack = load_employee_pack(session, str(row.source_employee_id or ""))
                manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
                sg, fg, ag = workspace_policy_from_manifest(manifest)
                ag = list(dict.fromkeys([*ag, *ag_snapshot, *ag_from_row]))
            except Exception:
                sg, fg, ag = [], [], list(dict.fromkeys([*ag_snapshot, *ag_from_row]))

            # 重新评估风险（DB 中可能是旧值）
            risk, reason = evaluate_risk(
                rel_path,
                content,
                scope_globs=sg,
                forbidden_globs=fg,
                approval_required_globs=ag,
            )
            row.risk_level = risk
            session.commit()

        if risk == "high":
            return {"auto_approved": False, "reason": f"high risk: {reason}"}

        if _require_ci() and risk != "low":
            return {
                "auto_approved": False,
                "reason": "waiting for CI (MODSTORE_AUTO_APPROVE_REQUIRE_CI)",
            }

        if risk == "medium":
            return {
                "auto_approved": False,
                "reason": f"medium risk requires manual approval: {reason}",
            }

        # risk == "low" → 窄 CI 验证（可通过 MODSTORE_AUTO_APPROVE_REQUIRE_CI 强制）
        narrow_ci: Dict[str, Any] = {"ok": True, "skipped": True}
        if _require_ci() or os.environ.get(
            "MODSTORE_CR_NARROW_CI_ENABLED", "1"
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            from modstore_server.cr_narrow_ci import (
                record_cr_validation_failure_for_evolution,
                run_narrow_ci_validation,
            )

            narrow_ci = run_narrow_ci_validation(rel_path, content)
            if not narrow_ci.get("ok") and not narrow_ci.get("skipped"):
                record_cr_validation_failure_for_evolution(
                    change_request_id=int(change_request_id),
                    source_employee_id=source_employee_id,
                    rel_path=rel_path,
                    validation=narrow_ci,
                )
                return {
                    "auto_approved": False,
                    "reason": f"narrow CI failed: {narrow_ci.get('failed_step')}",
                    "narrow_ci": narrow_ci,
                }

        # risk == "low" → 自动落盘
        from modstore_server.employee_change_request_service import apply_employee_change_request
        from modstore_server.models import User

        sf2 = get_session_factory()
        with sf2() as session:
            u = (
                session.query(User)
                .filter(User.is_admin == True)  # noqa: E712
                .order_by(User.id.asc())
                .first()
            )
            admin_id = int(u.id) if u else 0

        result = apply_employee_change_request(change_request_id, admin_id or 0)
        logger.info("auto_approve: CR %d auto-approved (risk=low): %s", change_request_id, reason)
        return {
            "auto_approved": True,
            "reason": reason,
            "result": result,
            "narrow_ci": narrow_ci,
        }

    except Exception as exc:
        logger.exception("maybe_auto_approve failed for CR %d", change_request_id)
        return {"auto_approved": False, "reason": str(exc)}


__all__ = ["evaluate_risk", "maybe_auto_approve"]
