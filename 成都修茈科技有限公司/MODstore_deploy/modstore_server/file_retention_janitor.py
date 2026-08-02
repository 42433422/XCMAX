"""档案清理员（``retention-officer``）的清理逻辑。

按 ``RETENTION_TARGETS`` 列出的目录与 TTL，删除过期文件 / 子目录，并把每次执行
写入 :class:`modstore_server.models.EmployeeExecutionMetric`，让员工大会在被问到
"过期文件谁清理" 时能直接引用最近一次执行流水。

默认 dry-run（``MODSTORE_RETENTION_DRY_RUN`` 不为 ``"0"`` 时即视为 dry-run），
首次发布建议保留 dry-run 至少 7 天再切换。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select

from modstore_server.models import EmployeeExecutionMetric, Notification, User, get_session_factory

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "retention-officer"

# 单次清理的硬上限：超过则停止并写 warning，避免误把整盘吃掉。
_MAX_RELEASED_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB
_NOISY_NOTIFICATION_KINDS = ("system", "employee_execution_done")

# 仓库根（``MODstore_deploy/`` 上一级）。
REPO_ROOT = Path(__file__).resolve().parents[2]

# 任何匹配以下绝对路径前缀 / 文件名片段的内容**禁止删除**：
_FORBIDDEN_PARTS = (
    "_local_secrets",
    "/secrets/",
    "/.git/",
)
_FORBIDDEN_NAME_PREFIXES = (".env",)


@dataclass
class RetentionTarget:
    """单条 TTL 目标声明。

    ``path``：相对仓库根的目录；不存在时跳过（不算 error）。
    ``ttl_days``：超过此 mtime 阈值的子项视为过期。
    ``glob``：只对匹配此 glob 的子项生效（默认 ``"*"`` 即所有子项）。
    ``recursive``：``True`` 时对每个匹配子项递归 ``rmtree``；``False`` 时仅
    对单文件 ``unlink``，目录被忽略。
    """

    path: str
    ttl_days: int
    glob: str = "*"
    recursive: bool = True
    description: str = ""


# 与 ``docs/runbooks/file-retention.md`` 同步。
RETENTION_TARGETS: List[RetentionTarget] = [
    RetentionTarget(
        path="MODstore_deploy/modstore_server/workbench_script_runs",
        ttl_days=7,
        glob="*",
        recursive=True,
        description="sandbox 单次 run 临时目录",
    ),
    RetentionTarget(
        path="MODstore_deploy/modstore_server/market_files/.tmp_chunks",
        ttl_days=1,
        glob="*",
        recursive=True,
        description="catalog 上传分片合并失败的残留",
    ),
    RetentionTarget(
        path="MODstore_deploy/modstore_server/webhook_events",
        ttl_days=30,
        glob="*.json",
        recursive=False,
        description="webhook 投递事件存档",
    ),
    RetentionTarget(
        path=".",
        ttl_days=14,
        glob=".cursor_*_log.txt",
        recursive=False,
        description="Cursor agent / smoke 日志",
    ),
    RetentionTarget(
        path="coverage",
        ttl_days=30,
        glob="*",
        recursive=True,
        description="历史 coverage 产物",
    ),
    RetentionTarget(
        path="playwright-report",
        ttl_days=30,
        glob="*",
        recursive=True,
        description="历史 playwright HTML 报告",
    ),
    RetentionTarget(
        path="test-results",
        ttl_days=30,
        glob="*",
        recursive=True,
        description="历史 e2e 失败截图 / 录像",
    ),
]


def is_dry_run() -> bool:
    raw = (os.environ.get("MODSTORE_RETENTION_DRY_RUN") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def prune_notifications(
    *,
    dry_run: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Bound derived notifications without deleting business evidence.

    Only high-volume operational ``system`` and ``employee_execution_done``
    rows are eligible. Payment and human-question notifications are never
    selected. A per-user/per-kind window prevents one noisy account from
    crowding out another account's recent alerts.
    """

    is_dry = is_dry_run() if dry_run is None else bool(dry_run)
    current = now or datetime.now(timezone.utc)
    system_keep = _bounded_env_int("MODSTORE_NOTIFICATION_SYSTEM_KEEP_PER_USER", 200, 10, 5000)
    execution_keep = _bounded_env_int(
        "MODSTORE_NOTIFICATION_EXECUTION_KEEP_PER_USER", 200, 10, 5000
    )
    ttl_days = _bounded_env_int("MODSTORE_NOTIFICATION_RETENTION_DAYS", 30, 7, 3650)
    max_delete = _bounded_env_int(
        "MODSTORE_NOTIFICATION_RETENTION_MAX_DELETE", 1_000_000, 1000, 1_000_000
    )
    cutoff = current - timedelta(days=ttl_days)

    ranked = (
        select(
            Notification.id.label("id"),
            Notification.kind.label("kind"),
            Notification.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=(Notification.user_id, Notification.kind),
                order_by=Notification.id.desc(),
            )
            .label("row_number"),
        )
        .where(Notification.kind.in_(_NOISY_NOTIFICATION_KINDS))
        .subquery()
    )
    candidate_filter = or_(
        ranked.c.created_at < cutoff,
        and_(ranked.c.kind == "system", ranked.c.row_number > system_keep),
        and_(
            ranked.c.kind == "employee_execution_done",
            ranked.c.row_number > execution_keep,
        ),
    )
    candidate_ids = select(ranked.c.id).where(candidate_filter)
    limited_ids = candidate_ids.order_by(ranked.c.id.asc()).limit(max_delete)

    sf = get_session_factory()
    with sf() as session:
        candidate_rows = candidate_ids.subquery()
        candidate_count = int(
            session.execute(select(func.count()).select_from(candidate_rows)).scalar_one() or 0
        )
        candidate_by_kind = {
            str(kind): int(count or 0)
            for kind, count in session.execute(
                select(ranked.c.kind, func.count()).where(candidate_filter).group_by(ranked.c.kind)
            ).all()
        }
        selected_count = min(candidate_count, max_delete)
        removed = 0
        if not is_dry and selected_count:
            removed = int(
                session.query(Notification)
                .filter(Notification.id.in_(limited_ids))
                .delete(synchronize_session=False)
                or 0
            )
            session.commit()

    return {
        "ok": True,
        "dry_run": is_dry,
        "candidate_count": candidate_count,
        "candidate_by_kind": candidate_by_kind,
        "removed_count": removed,
        "selected_count": selected_count,
        "truncated": candidate_count > max_delete,
        "max_delete": max_delete,
        "ttl_days": ttl_days,
        "keep_per_user": {
            "system": system_keep,
            "employee_execution_done": execution_keep,
        },
        "eligible_kinds": list(_NOISY_NOTIFICATION_KINDS),
        "vacuum_recommended": removed > 0,
    }


def _is_forbidden(path: Path) -> bool:
    """护栏：禁止删除 secrets / .git / .env 等敏感目录。"""
    p = str(path).replace("\\", "/")
    if any(part in p for part in _FORBIDDEN_PARTS):
        return True
    name = path.name
    return any(name.startswith(prefix) for prefix in _FORBIDDEN_NAME_PREFIXES)


def _path_inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
    except (OSError, ValueError):
        return False
    return True


def _entry_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += int(child.stat().st_size)
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _entry_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


# 仅这些条目应拉高整次执行的 metric status（空目录 / 无可删文件不算）。
_ACTIONABLE_WARNING_MARKERS = (
    "glob 失败",
    "删除失败",
    "路径不在仓库",
    "达到单次清理上限",
    "命中禁区",
)


def _is_actionable_warning(msg: str) -> bool:
    text = (msg or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _ACTIONABLE_WARNING_MARKERS)


@dataclass
class TargetReport:
    path: str
    ttl_days: int
    glob: str
    recursive: bool
    description: str
    exists: bool = True
    candidate_count: int = 0
    kept: int = 0
    removed: int = 0
    skipped: int = 0
    released_bytes: int = 0
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "ttl_days": self.ttl_days,
            "glob": self.glob,
            "recursive": self.recursive,
            "description": self.description,
            "exists": bool(self.exists),
            "candidate_count": int(self.candidate_count),
            "kept": int(self.kept),
            "removed": int(self.removed),
            "skipped": int(self.skipped),
            "released_bytes": int(self.released_bytes),
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }


def _process_target(
    target: RetentionTarget,
    *,
    repo_root: Path,
    dry_run: bool,
    cumulative_released: int,
) -> TargetReport:
    rep = TargetReport(
        path=target.path,
        ttl_days=int(target.ttl_days),
        glob=target.glob,
        recursive=bool(target.recursive),
        description=target.description,
    )
    base = (repo_root / target.path).resolve()
    if not base.exists():
        rep.exists = False
        rep.notes.append("目录不存在（跳过，非异常）")
        logger.debug("retention: target missing path=%s", target.path)
        return rep
    if not _path_inside_repo(base):
        rep.warnings.append("路径不在仓库内，跳过")
        return rep

    cutoff_ts = time.time() - max(0, int(target.ttl_days)) * 86400.0

    # 用 ``glob`` 匹配第一级子项（与 RETENTION_TARGETS 表语义一致）。
    try:
        candidates = sorted(base.glob(target.glob))
    except OSError as exc:
        rep.warnings.append(f"glob 失败：{exc}")
        return rep

    rep.candidate_count = len(candidates)

    for entry in candidates:
        if entry == base:
            continue
        if _is_forbidden(entry):
            rep.skipped += 1
            rep.warnings.append(f"命中禁区，跳过：{entry.name}")
            continue
        if not _path_inside_repo(entry):
            rep.skipped += 1
            continue
        if entry.is_dir() and not target.recursive:
            rep.kept += 1
            continue

        mtime = _entry_mtime(entry)
        if mtime <= 0 or mtime > cutoff_ts:
            rep.kept += 1
            continue

        size = _entry_size_bytes(entry)
        # 单次执行硬上限：超过 5 GiB 立即停止扫描该 target。
        if cumulative_released + rep.released_bytes + size > _MAX_RELEASED_BYTES:
            rep.warnings.append(
                f"达到单次清理上限 {_MAX_RELEASED_BYTES // (1024 ** 3)} GiB，停止此 target"
            )
            break

        if dry_run:
            rep.removed += 1
            rep.released_bytes += size
            continue

        try:
            if entry.is_file() or entry.is_symlink():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry, ignore_errors=False)
            rep.removed += 1
            rep.released_bytes += size
        except OSError as exc:
            rep.skipped += 1
            rep.warnings.append(f"删除失败 {entry.name}：{exc}")

    return rep


def _resolve_admin_user_id() -> int:
    """优先取最早创建的管理员；没有管理员时取最早的用户；都没有时返回 0（不写流水）。"""
    sf = get_session_factory()
    with sf() as db:
        admin = (
            db.query(User)
            .filter(User.is_admin == True)  # noqa: E712
            .order_by(User.id.asc())
            .first()
        )
        if admin:
            return int(admin.id)
        any_user = db.query(User).order_by(User.id.asc()).first()
        return int(any_user.id) if any_user else 0


def _write_metric(
    *,
    user_id: int,
    task: str,
    status: str,
    duration_ms: float,
    error: str = "",
) -> Optional[int]:
    """把一次清理写入 ``EmployeeExecutionMetric``（``user_id == 0`` 时跳过）。"""
    if user_id <= 0:
        logger.warning("retention janitor: 找不到任何用户，跳过流水写入")
        return None
    sf = get_session_factory()
    with sf() as db:
        metric = EmployeeExecutionMetric(
            user_id=user_id,
            employee_id=EMPLOYEE_ID,
            task=task[:128],
            status=status[:32],
            duration_ms=float(duration_ms),
            llm_tokens=0,
            error=(error or "")[:4000],
        )
        db.add(metric)
        db.commit()
        return int(metric.id)


def _format_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(max(0, int(n)))
    for unit in units:
        if f < 1024.0:
            return f"{f:.1f} {unit}"
        f /= 1024.0
    return f"{f:.1f} PiB"


def _build_report_md(
    *,
    dry_run: bool,
    targets: List[TargetReport],
    total_released: int,
    total_removed: int,
    duration_ms: float,
) -> str:
    head = "# 档案清理执行报告"
    mode = "**dry-run（仅预览）**" if dry_run else "**真实删除**"
    lines = [
        head,
        "",
        f"- 模式：{mode}",
        f"- 已清理目标数：{len(targets)}",
        f"- 累计删除条目：{total_removed}",
        f"- 累计释放空间：{_format_bytes(total_released)}",
        f"- 耗时：{duration_ms:.1f} ms",
        "",
        "## 各目标明细",
        "",
        "| 目录 | TTL（天） | 删除 | 保留 | 释放 | 备注 |",
        "|------|-----------|------|------|------|------|",
    ]
    for r in targets:
        parts: List[str] = []
        if not r.exists:
            parts.append("目录不存在")
        if r.notes:
            parts.extend(r.notes)
        if r.warnings:
            parts.extend(r.warnings)
        remark = "; ".join(parts) if parts else "—"
        lines.append(
            f"| `{r.path}` | {r.ttl_days} | {r.removed} | {r.kept} | "
            f"{_format_bytes(r.released_bytes)} | {remark} |"
        )
    return "\n".join(lines) + "\n"


def run_retention_janitor(
    *,
    dry_run: Optional[bool] = None,
    notification_dry_run: Optional[bool] = None,
) -> Dict[str, Any]:
    """执行一次清理。

    CLI 和普通调用默认让数据库保留跟随文件 ``dry_run``。调度器可以单独
    传入 ``notification_dry_run``，使派生通知按保留契约自动清理，而文件目标
    仍保持预演。
    """
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    is_dry = is_dry_run() if dry_run is None else bool(dry_run)
    database_is_dry = is_dry if notification_dry_run is None else bool(notification_dry_run)

    target_reports: List[TargetReport] = []
    cumulative_released = 0
    overall_warnings: List[str] = []
    error_text = ""
    database_retention: Dict[str, Any] = {}
    try:
        for target in RETENTION_TARGETS:
            rep = _process_target(
                target,
                repo_root=REPO_ROOT,
                dry_run=is_dry,
                cumulative_released=cumulative_released,
            )
            cumulative_released += rep.released_bytes
            target_reports.append(rep)
    except Exception as exc:  # noqa: BLE001
        logger.exception("retention janitor failed")
        error_text = str(exc)[:1000]

    try:
        database_retention = prune_notifications(dry_run=database_is_dry)
    except Exception as exc:  # noqa: BLE001
        logger.exception("notification retention failed")
        database_retention = {
            "ok": False,
            "dry_run": database_is_dry,
            "candidate_count": 0,
            "removed_count": 0,
            "error": str(exc)[:1000],
        }
        if not error_text:
            error_text = "notification retention failed: " + str(exc)[:900]

    duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    total_removed = sum(r.removed for r in target_reports)
    total_released = sum(r.released_bytes for r in target_reports)
    actionable_warnings: List[str] = list(overall_warnings)
    for r in target_reports:
        for w in r.warnings:
            if _is_actionable_warning(w):
                actionable_warnings.append(w)
    has_actionable_warning = bool(actionable_warnings)

    if error_text:
        status = "failed"
    elif has_actionable_warning:
        status = "warning"
    else:
        status = "success"

    logger.info(
        "retention janitor: dry_run=%s status=%s targets=%d removed=%d released=%s "
        "duration_ms=%.1f actionable_warnings=%d",
        is_dry,
        status,
        len(target_reports),
        total_removed,
        _format_bytes(total_released),
        duration_ms,
        len(actionable_warnings),
    )

    report_md = _build_report_md(
        dry_run=is_dry,
        targets=target_reports,
        total_released=total_released,
        total_removed=total_removed,
        duration_ms=duration_ms,
    )
    report_md += (
        "\n## 数据库通知保留\n\n"
        f"- 模式：{'dry-run' if database_is_dry else '真实清理'}\n"
        f"- 候选：{int(database_retention.get('candidate_count') or 0)} 条\n"
        f"- 已删除：{int(database_retention.get('removed_count') or 0)} 条\n"
        f"- 仅处理：{', '.join(database_retention.get('eligible_kinds') or _NOISY_NOTIFICATION_KINDS)}\n"
    )

    user_id = _resolve_admin_user_id()
    metric_id: Optional[int] = None
    try:
        metric_id = _write_metric(
            user_id=user_id,
            task=("janitor.scheduled.dry_run" if is_dry else "janitor.scheduled"),
            status=status,
            duration_ms=duration_ms,
            error=error_text,
        )
    except Exception:  # noqa: BLE001
        logger.exception("retention janitor: write metric failed")

    result = {
        "ok": status != "failed",
        "status": status,
        "dry_run": is_dry,
        "started_at": started_at.isoformat() + "Z",
        "duration_ms": duration_ms,
        "removed_count": total_removed,
        "released_bytes": total_released,
        "database_retention": database_retention,
        "scanned_targets": [r.to_dict() for r in target_reports],
        "warnings": actionable_warnings,
        "error": error_text,
        "report_md": report_md,
        "metric_id": metric_id,
        "employee_id": EMPLOYEE_ID,
    }
    _record_retention_runtime(result)
    return result


def _record_retention_runtime(result: Dict[str, Any]) -> None:
    try:
        from modstore_server.time_rail_runtime import record_node_run

        record_node_run(
            "R",
            ok=bool(result.get("ok")),
            source="file_retention_janitor",
            meta={
                "status": result.get("status"),
                "dry_run": result.get("dry_run"),
                "metric_id": result.get("metric_id"),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("retention janitor: time_rail runtime record failed")


def _cli() -> int:
    """``python -m modstore_server.file_retention_janitor`` 入口。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="MODstore retention janitor")
    parser.add_argument("--apply", action="store_true", help="真实删除（默认 dry-run）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    dry = not args.apply
    if not dry:
        os.environ["MODSTORE_RETENTION_DRY_RUN"] = "0"

    result = run_retention_janitor(dry_run=dry)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["report_md"])
        if result.get("warnings"):
            print("WARNINGS:", result["warnings"])
        if result.get("error"):
            print("ERROR:", result["error"])
            return 1
    return 0


def cleanup_employee_workspaces() -> Dict[str, Any]:
    """清理过期员工工作区文件（由定时任务或 janitor 主流程调用）。"""
    try:
        from modstore_server.employee_workspace_manager import cleanup_expired_workspaces

        result = cleanup_expired_workspaces()
        logger.info("janitor: workspace cleanup: %s", result)
        return result
    except Exception as exc:
        logger.exception("janitor: workspace cleanup failed")
        return {"cleaned_files": 0, "error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(_cli())
