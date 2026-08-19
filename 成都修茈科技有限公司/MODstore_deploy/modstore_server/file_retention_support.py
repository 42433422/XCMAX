"""Database retention, reporting, and metrics for the file janitor."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select

from modstore_server.models import EmployeeExecutionMetric, Notification, User, get_session_factory

logger = logging.getLogger(__name__)

NOISY_NOTIFICATION_KINDS = ("system", "employee_execution_done")
EMPLOYEE_ID = "retention-officer"


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
    """Bound derived notifications without deleting business evidence."""
    from modstore_server.file_retention_janitor import is_dry_run

    dry = is_dry_run() if dry_run is None else bool(dry_run)
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
        .where(Notification.kind.in_(NOISY_NOTIFICATION_KINDS))
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
    session_factory = get_session_factory()
    with session_factory() as session:
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
        if not dry and selected_count:
            removed = int(
                session.query(Notification)
                .filter(Notification.id.in_(limited_ids))
                .delete(synchronize_session=False)
                or 0
            )
            session.commit()
    return {
        "ok": True,
        "dry_run": dry,
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
        "eligible_kinds": list(NOISY_NOTIFICATION_KINDS),
        "vacuum_recommended": removed > 0,
    }


def resolve_admin_user_id() -> int:
    """Resolve the oldest admin, then the oldest user, for metric ownership."""
    session_factory = get_session_factory()
    with session_factory() as database:
        admin = (
            database.query(User)
            .filter(User.is_admin == True)  # noqa: E712
            .order_by(User.id.asc())
            .first()
        )
        if admin:
            return int(admin.id)
        any_user = database.query(User).order_by(User.id.asc()).first()
        return int(any_user.id) if any_user else 0


def write_metric(
    *,
    user_id: int,
    task: str,
    status: str,
    duration_ms: float,
    error: str = "",
) -> Optional[int]:
    if user_id <= 0:
        logger.warning("retention janitor: 找不到任何用户，跳过流水写入")
        return None
    session_factory = get_session_factory()
    with session_factory() as database:
        metric = EmployeeExecutionMetric(
            user_id=user_id,
            employee_id=EMPLOYEE_ID,
            task=task[:128],
            status=status[:32],
            duration_ms=float(duration_ms),
            llm_tokens=0,
            error=(error or "")[:4000],
        )
        database.add(metric)
        database.commit()
        return int(metric.id)


def format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(max(0, int(size)))
    for unit in units:
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PiB"


def build_report_md(
    *,
    dry_run: bool,
    targets: List[Any],
    total_released: int,
    total_removed: int,
    duration_ms: float,
) -> str:
    mode = "**dry-run（仅预览）**" if dry_run else "**真实删除**"
    lines = [
        "# 档案清理执行报告",
        "",
        f"- 模式：{mode}",
        f"- 已清理目标数：{len(targets)}",
        f"- 累计删除条目：{total_removed}",
        f"- 累计释放空间：{format_bytes(total_released)}",
        f"- 耗时：{duration_ms:.1f} ms",
        "",
        "## 各目标明细",
        "",
        "| 目录 | TTL（天） | 删除 | 保留 | 释放 | 备注 |",
        "|------|-----------|------|------|------|------|",
    ]
    for report in targets:
        notes: List[str] = []
        if not report.exists:
            notes.append("目录不存在")
        notes.extend(report.notes)
        notes.extend(report.warnings)
        remark = "; ".join(notes) if notes else "—"
        lines.append(
            f"| `{report.path}` | {report.ttl_days} | {report.removed} | {report.kept} | "
            f"{format_bytes(report.released_bytes)} | {remark} |"
        )
    return "\n".join(lines) + "\n"


def record_retention_runtime(result: Dict[str, Any]) -> None:
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
    except Exception:
        logger.exception("retention janitor: time_rail runtime record failed")
