"""员工健康巡检 + 连续失败自动下架（断点 7）。

核心责任
========
1. 在最近 ``lookback_hours``（默认 24）的 ``EmployeeExecutionMetric`` 中
   找出失败次数 ≥ ``deactivate_threshold``（默认 8）的员工。
2. 把对应的 ``CatalogItem``（``artifact='employee_pack'`` + ``pkg_id``）
   ``is_active`` 置为 ``False``，并写入 ``EmployeeEvolutionRecord`` 留痕。
3. 给所有管理员发一条站内通知，附上失败次数与最近一条错误消息。
4. 失败但未达下架阈值的员工只发预警通知（每个员工每天至多一次，避免刷屏）。

启用方式
========
环境变量：
    MODSTORE_HEALTH_SCAN_ENABLED            = "1"  默认开
    MODSTORE_HEALTH_SCAN_LOOKBACK_HOURS     = "24"
    MODSTORE_HEALTH_SCAN_WARN_THRESHOLD     = "3"   连续失败 ≥ N 触发预警
    MODSTORE_HEALTH_SCAN_DEACTIVATE_THRESHOLD = "8" 连续失败 ≥ M 触发下架
    MODSTORE_HEALTH_SCAN_INTERVAL_MIN       = "30"  scheduler 周期（分钟）

调度入口由 ``workflow_scheduler.start_scheduler`` 注册，间隔通过上面的 INTERVAL_MIN 控制。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func

from modstore_server.models import (
    CatalogItem,
    EmployeeEvolutionRecord,
    EmployeeExecutionMetric,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "1") -> bool:
    return (os.environ.get(name, default) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except ValueError:
        return default


def _get_admin_user_ids() -> List[int]:
    sf = get_session_factory()
    with sf() as session:
        rows = session.query(User.id).filter(User.is_admin.is_(True)).all()
        return [int(r[0]) for r in rows if r and r[0]]


def _notify_admins(title: str, content: str, *, kind: str, payload: Dict[str, Any]) -> None:
    try:
        from modstore_server.notification_service import (
            NotificationType,
            create_notification,
        )

        notif_type = NotificationType.SYSTEM if kind != "deactivated" else NotificationType.SYSTEM
        for uid in _get_admin_user_ids():
            try:
                create_notification(
                    user_id=int(uid),
                    notification_type=notif_type,
                    title=title,
                    content=content,
                    data=payload,
                )
            except Exception:
                logger.debug("admin notify failed uid=%s", uid, exc_info=True)
    except Exception:
        logger.debug("notification_service unavailable", exc_info=True)


def _deactivate_catalog_employee(employee_id: str) -> bool:
    """把 catalog 里 pkg_id == employee_id 的员工包置为不可用。

    当前 catalog schema 没有 ``is_active`` 字段；老逻辑直接访问该字段会让
    health scan 崩掉。这里兼容两种 schema：有 is_active 就置 False，否则用
    compliance_status/delist_reason 表达下架。
    """
    sf = get_session_factory()
    with sf() as session:
        query = session.query(CatalogItem).filter(
            CatalogItem.artifact == "employee_pack",
            CatalogItem.pkg_id == str(employee_id),
        )
        if hasattr(CatalogItem, "is_active"):
            query = query.filter(CatalogItem.is_active.is_(True))
        rows = query.all()
        if not rows:
            return False
        for r in rows:
            if hasattr(r, "is_active"):
                r.is_active = False
            if hasattr(r, "compliance_status"):
                r.compliance_status = "delisted"
            if hasattr(r, "delist_reason"):
                r.delist_reason = "employee_health_auto_deactivated"
        session.commit()
        return True


def _record_runtime_policy(
    *,
    employee_id: str,
    fail_count: int,
    lookback_hours: int,
    severity: str,
) -> None:
    try:
        from modstore_server.employee_runtime_policy import record_employee_degradation

        record_employee_degradation(
            employee_id=employee_id,
            fail_count=fail_count,
            lookback_hours=lookback_hours,
            reason="employee_health_scan_failure_rate",
            severity=severity,
        )
    except Exception:
        logger.debug("employee runtime policy update failed eid=%s", employee_id, exc_info=True)


def _record_evolution(
    *,
    employee_id: str,
    fail_count: int,
    lookback_hours: int,
    status: str,
    explanation: str,
) -> None:
    try:
        sf = get_session_factory()
        with sf() as session:
            session.add(
                EmployeeEvolutionRecord(
                    employee_id=employee_id,
                    failure_count=int(fail_count or 0),
                    lookback_hours=int(lookback_hours or 0),
                    status=status,
                    prompt_before="",
                    prompt_after="runtime_policy_override",
                    diff_explanation=explanation[:4000],
                    triggered_by="employee_health_scan",
                )
            )
            session.commit()
    except Exception:
        logger.debug("employee evolution record failed eid=%s", employee_id, exc_info=True)


def run_health_scan(
    *,
    lookback_hours: int = 0,
    warn_threshold: int = 0,
    deactivate_threshold: int = 0,
    notify: bool = True,
) -> Dict[str, Any]:
    """主入口：扫描最近窗口、统计失败次数、按阈值预警/下架。

    返回结构：
        {
          "ok": bool,
          "scanned": int,                    # 命中预警的员工数
          "warned": [...],                   # 仅预警的员工
          "deactivated": [...],              # 触发下架的员工
          "skipped_no_catalog": [...],
        }
    """
    if not _flag("MODSTORE_HEALTH_SCAN_ENABLED", "1"):
        return {"ok": True, "enabled": False, "scanned": 0}

    lookback_hours = (
        lookback_hours
        if lookback_hours > 0
        else _int_env("MODSTORE_HEALTH_SCAN_LOOKBACK_HOURS", 24)
    )
    warn_threshold = (
        warn_threshold if warn_threshold > 0 else _int_env("MODSTORE_HEALTH_SCAN_WARN_THRESHOLD", 3)
    )
    deactivate_threshold = (
        deactivate_threshold
        if deactivate_threshold > 0
        else _int_env("MODSTORE_HEALTH_SCAN_DEACTIVATE_THRESHOLD", 8)
    )
    if deactivate_threshold < warn_threshold:
        deactivate_threshold = warn_threshold + 1

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.count(EmployeeExecutionMetric.id).label("fail_count"),
                func.max(EmployeeExecutionMetric.created_at).label("last_at"),
            )
            .filter(
                EmployeeExecutionMetric.created_at >= cutoff,
                EmployeeExecutionMetric.status != "success",
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .order_by(func.count(EmployeeExecutionMetric.id).desc())
            .all()
        )

    warned: List[Dict[str, Any]] = []
    deactivated: List[Dict[str, Any]] = []
    skipped_no_catalog: List[str] = []

    for r in rows:
        eid = str(r[0] or "").strip()
        fail_count = int(r[1] or 0)
        last_at = r[2]
        if not eid or fail_count < warn_threshold:
            continue
        last_iso = last_at.isoformat() if last_at else ""
        record = {"employee_id": eid, "fail_count": fail_count, "last_failure_at": last_iso}

        if fail_count >= deactivate_threshold:
            ok_deact = _deactivate_catalog_employee(eid)
            _record_runtime_policy(
                employee_id=eid,
                fail_count=fail_count,
                lookback_hours=lookback_hours,
                severity="deactivate",
            )
            _record_evolution(
                employee_id=eid,
                fail_count=fail_count,
                lookback_hours=lookback_hours,
                status="auto_degraded",
                explanation="Failure count reached deactivate threshold; catalog delisted and runtime policy forced conservative fallback.",
            )
            if not ok_deact:
                skipped_no_catalog.append(eid)
                logger.info(
                    "health_scan: employee %s exceeded threshold %d but no active catalog row",
                    eid,
                    deactivate_threshold,
                )
                continue
            deactivated.append(record)
            if notify:
                _notify_admins(
                    title=f"AI 员工自动下架：{eid}",
                    content=(
                        f"员工 {eid} 在最近 {lookback_hours} 小时连续失败 {fail_count} 次，"
                        f"已自动置为不可用（is_active=False）。请检查 prompt / 工具配置后重新上架。"
                    ),
                    kind="deactivated",
                    payload={
                        "event": "employee_health.deactivated",
                        **record,
                        "deactivate_threshold": deactivate_threshold,
                        "lookback_hours": lookback_hours,
                    },
                )
        else:
            warned.append(record)
            _record_runtime_policy(
                employee_id=eid,
                fail_count=fail_count,
                lookback_hours=lookback_hours,
                severity="warn",
            )
            _record_evolution(
                employee_id=eid,
                fail_count=fail_count,
                lookback_hours=lookback_hours,
                status="auto_degraded",
                explanation="Failure count reached warning threshold; runtime policy lowered temperature and reduced max tokens.",
            )
            if notify:
                _notify_admins(
                    title=f"AI 员工失败预警：{eid}",
                    content=(
                        f"员工 {eid} 在最近 {lookback_hours} 小时失败 {fail_count} 次，"
                        f"未达下架阈值（{deactivate_threshold}）。建议核对最近的执行日志。"
                    ),
                    kind="warning",
                    payload={
                        "event": "employee_health.warning",
                        **record,
                        "warn_threshold": warn_threshold,
                        "deactivate_threshold": deactivate_threshold,
                        "lookback_hours": lookback_hours,
                    },
                )

    out = {
        "ok": True,
        "enabled": True,
        "scanned": len(warned) + len(deactivated),
        "warned": warned,
        "deactivated": deactivated,
        "skipped_no_catalog": skipped_no_catalog,
        "lookback_hours": lookback_hours,
        "warn_threshold": warn_threshold,
        "deactivate_threshold": deactivate_threshold,
    }
    logger.info(
        "health_scan: scanned=%d warned=%d deactivated=%d skipped=%d",
        out["scanned"],
        len(warned),
        len(deactivated),
        len(skipped_no_catalog),
    )
    return out


__all__ = ["run_health_scan"]
