"""员工成绩单：聚合 EmployeeExecutionMetric 给老板看「这员工到底有没有用」。

对应「10 项成熟度要求」第 8 项 — 会承担结果：
每个员工要有最近任务、成功率、失败原因、处理时长、影响范围。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func

from modstore_server.models import get_session_factory


def _ensure_aware(x: Any) -> str:
    return str(x or "").strip()


def _build_recent_task_list(rows: List[Any], limit: int = 5) -> List[Dict[str, Any]]:
    """把 metric 行转成最近任务摘要列表（不含敏感上下文）。"""
    out: List[Dict[str, Any]] = []
    for r in rows[:limit]:
        out.append(
            {
                "id": int(r.id),
                "task": _ensure_aware(r.task)[:128],
                "status": _ensure_aware(r.status),
                "duration_ms": float(r.duration_ms or 0.0),
                "llm_tokens": int(r.llm_tokens or 0),
                "failure_kind": _ensure_aware(r.failure_kind),
                "error_preview": _ensure_aware(r.error)[:200],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def get_employee_scorecard(
    employee_id: str,
    *,
    days: int = 7,
    limit_recent: int = 5,
) -> Dict[str, Any]:
    """单个员工的成绩单。

    返回字段：
      employee_id, window_days, total_tasks, success_count, failure_count,
      success_rate, avg_duration_ms, p95_duration_ms, total_llm_tokens,
      failure_breakdown(top failure_kind), recent_tasks, last_run_at

    任何异常都吞掉返回 ok=False，避免影响调用方。
    """
    try:
        days = max(1, min(int(days), 90))
        limit_recent = max(1, min(int(limit_recent), 50))
    except (TypeError, ValueError):
        days, limit_recent = 7, 5

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sf = get_session_factory()
    with sf() as session:
        from modstore_server.models_user import EmployeeExecutionMetric

        base_q = session.query(EmployeeExecutionMetric).filter(
            EmployeeExecutionMetric.employee_id == employee_id,
            EmployeeExecutionMetric.created_at >= cutoff,
        )

        total = int(base_q.count() or 0)
        if total == 0:
            return {
                "ok": True,
                "employee_id": employee_id,
                "window_days": days,
                "total_tasks": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
                "total_llm_tokens": 0,
                "failure_breakdown": [],
                "recent_tasks": [],
                "last_run_at": None,
                "note": "时间窗内无执行记录",
            }

        success_count = int(base_q.filter(EmployeeExecutionMetric.status == "success").count() or 0)
        failure_count = total - success_count

        # 失败原因 top N（按 failure_kind 聚合）
        fail_rows = (
            session.query(
                EmployeeExecutionMetric.failure_kind,
                func.count(EmployeeExecutionMetric.id),
            )
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.created_at >= cutoff,
                EmployeeExecutionMetric.status != "success",
            )
            .group_by(EmployeeExecutionMetric.failure_kind)
            .order_by(func.count(EmployeeExecutionMetric.id).desc())
            .limit(5)
            .all()
        )
        failure_breakdown = [
            {"failure_kind": _ensure_aware(k) or "unknown", "count": int(c)} for k, c in fail_rows
        ]

        # 平均处理时长
        avg_duration = float(
            session.query(func.avg(EmployeeExecutionMetric.duration_ms))
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .scalar()
            or 0.0
        )

        # P95 处理时长：用百分位近似（取窗口内按 duration_ms 降序后第 95% 位置）
        durations = (
            session.query(EmployeeExecutionMetric.duration_ms)
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .order_by(EmployeeExecutionMetric.duration_ms.asc())
            .all()
        )
        p95 = 0.0
        if durations:
            idx = max(0, min(len(durations) - 1, int(len(durations) * 0.95)))
            p95 = float(durations[idx][0] or 0.0)

        total_tokens = int(
            session.query(func.sum(EmployeeExecutionMetric.llm_tokens))
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .scalar()
            or 0
        )

        recent_rows = base_q.order_by(EmployeeExecutionMetric.id.desc()).limit(limit_recent).all()
        recent_tasks = _build_recent_task_list(recent_rows, limit=limit_recent)

        last_row = (
            session.query(EmployeeExecutionMetric.created_at)
            .filter(EmployeeExecutionMetric.employee_id == employee_id)
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(1)
            .first()
        )
        last_run_at = last_row[0].isoformat() if last_row and last_row[0] else None

    return {
        "ok": True,
        "employee_id": employee_id,
        "window_days": days,
        "total_tasks": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_count / total, 4) if total else 0.0,
        "avg_duration_ms": round(avg_duration, 1),
        "p95_duration_ms": round(p95, 1),
        "total_llm_tokens": total_tokens,
        "failure_breakdown": failure_breakdown,
        "recent_tasks": recent_tasks,
        "last_run_at": last_run_at,
    }


def list_all_employee_scorecards(
    *,
    days: int = 7,
    top_n: int = 50,
    sort_by: str = "total_tasks",
) -> Dict[str, Any]:
    """全部员工成绩汇总（按 sort_by 排序，默认按任务量降序）。

    用于老板「一览谁在干活、谁在拖后腿」。

    返回字段：
      window_days, total_employees, sorted_by, items: [{employee_id, total_tasks, success_rate, ...}]
    """
    try:
        days = max(1, min(int(days), 90))
        top_n = max(1, min(int(top_n), 200))
    except (TypeError, ValueError):
        days, top_n = 7, 50

    valid_sort = {
        "total_tasks",
        "success_rate",
        "avg_duration_ms",
        "failure_count",
        "total_llm_tokens",
    }
    if sort_by not in valid_sort:
        sort_by = "total_tasks"

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sf = get_session_factory()
    with sf() as session:
        from modstore_server.models_user import EmployeeExecutionMetric

        # 直接拉原始行聚合（员工 < 100，量级可接受，跨方言兼容性更好）
        all_rows = (
            session.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.created_at >= cutoff)
            .all()
        )

    by_emp: Dict[str, Dict[str, Any]] = {}
    for r in all_rows:
        eid = _ensure_aware(r.employee_id)
        if not eid:
            continue
        agg = by_emp.setdefault(
            eid,
            {
                "employee_id": eid,
                "total_tasks": 0,
                "success_count": 0,
                "failure_count": 0,
                "total_duration_ms": 0.0,
                "total_llm_tokens": 0,
                "failure_kinds": Counter(),
                "last_run_at": None,
            },
        )
        agg["total_tasks"] += 1
        if _ensure_aware(r.status) == "success":
            agg["success_count"] += 1
        else:
            agg["failure_count"] += 1
            fk = _ensure_aware(r.failure_kind) or "unknown"
            agg["failure_kinds"][fk] += 1
        agg["total_duration_ms"] += float(r.duration_ms or 0.0)
        agg["total_llm_tokens"] += int(r.llm_tokens or 0)
        ts = r.created_at
        if ts:
            cur = agg["last_run_at"]
            if cur is None or ts.isoformat() > cur:
                agg["last_run_at"] = ts.isoformat()

    items: List[Dict[str, Any]] = []
    for agg in by_emp.values():
        total = agg["total_tasks"]
        success = agg["success_count"]
        items.append(
            {
                "employee_id": agg["employee_id"],
                "total_tasks": total,
                "success_count": success,
                "failure_count": agg["failure_count"],
                "success_rate": round(success / total, 4) if total else 0.0,
                "avg_duration_ms": round(agg["total_duration_ms"] / total, 1) if total else 0.0,
                "total_llm_tokens": agg["total_llm_tokens"],
                "top_failure_kind": (
                    agg["failure_kinds"].most_common(1)[0][0] if agg["failure_kinds"] else ""
                ),
                "last_run_at": agg["last_run_at"],
            }
        )

    # 排序
    items.sort(key=lambda x: x.get(sort_by, 0), reverse=True)
    items = items[:top_n]

    return {
        "ok": True,
        "window_days": days,
        "total_employees": len(by_emp),
        "sorted_by": sort_by,
        "items": items,
    }


def build_human_friendly_scorecard_text(employee_id: str, days: int = 7) -> str:
    """把 scorecard 转成老板能看的简短中文汇报。

    用于「10 项说人话」第 8 项 — 不让老板看 JSON，看人话。
    """
    sc = get_employee_scorecard(employee_id, days=days)
    if not sc.get("ok"):
        return f"{employee_id}：查询成绩单失败"

    if sc.get("total_tasks", 0) == 0:
        return f"{employee_id}：最近 {days} 天 0 任务，未派活或无执行记录。"

    rate = sc["success_rate"]
    rate_pct = f"{rate * 100:.1f}%"
    total = sc["total_tasks"]
    fail = sc["failure_count"]
    avg = sc["avg_duration_ms"]
    p95 = sc["p95_duration_ms"]
    tok = sc["total_llm_tokens"]

    fb = sc.get("failure_breakdown") or []
    if fb:
        fb_top = ", ".join(f"{x['failure_kind']}×{x['count']}" for x in fb[:3])
    else:
        fb_top = "无"

    last = sc.get("last_run_at") or "无记录"

    return (
        f"{employee_id}（最近 {days} 天）："
        f"共 {total} 个任务，成功 {rate_pct}，失败 {fail}；"
        f"平均耗时 {avg:.0f}ms / P95 {p95:.0f}ms；"
        f"消耗 token {tok}；"
        f"失败原因 top：{fb_top}；"
        f"上次执行：{last}。"
    )


__all__ = [
    "get_employee_scorecard",
    "list_all_employee_scorecards",
    "build_human_friendly_scorecard_text",
]
