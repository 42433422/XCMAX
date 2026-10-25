"""Read employee catalog membership, execution history, and pending changes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from sqlalchemy import desc

from modstore_server.all_hands_policy import clamp_all_hands_max_employees
from modstore_server.all_hands_ports import SessionProvider
from modstore_server.models import CatalogItem, EmployeeExecutionMetric
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AllHandsRepository:
    session_provider: SessionProvider
    planned_ids: Callable[[], frozenset[str]]
    clamp: Callable[[int], int] = clamp_all_hands_max_employees

    def employee_pairs(
        self, requested_ids: Optional[List[str]], *, max_employees: int
    ) -> List[Tuple[str, str]]:
        """返回 ``[(pkg_id, display_name), ...]``。

        **编制员工**（``duty_roster.all_planned_employee_ids``）与公开市场无关：不要求
        ``catalog_items.is_public``，也不要求已做「市场上架」。只要能加载员工包即可：

        - Postgres ``catalog_items`` 中 ``artifact=employee_pack``；**或**
        - XC 本地 ``catalog_store.packages.json`` 中已登记 ``artifact=employee_pack`` 且
          ``files/`` 下有对应 zip（与 :func:`modstore_server.employee_runtime.load_employee_pack` 一致）。
        """
        roster = self.planned_ids()
        from modstore_server.catalog_store import employee_pack_records_from_store

        xc = employee_pack_records_from_store()
        sf = self.session_provider()
        with sf() as session:
            rows: Any = (
                session.query(CatalogItem.pkg_id, CatalogItem.name)
                .filter_by(artifact="employee_pack")
                .all()
            )
        db_ids = {str(r[0]) for r in rows}
        name_by_id = {str(r[0]): str(r[1] or r[0]) for r in rows}
        for pid, rec in xc.items():
            if pid not in name_by_id:
                name_by_id[pid] = str(rec.get("name") or pid).strip() or pid
        xc_ids = set(xc.keys())
        available = db_ids | xc_ids
        if requested_ids:
            pairs: List[Tuple[str, str]] = []
            for pid in requested_ids:
                pid = str(pid or "").strip()
                if not pid or pid not in available:
                    continue
                pairs.append((pid, name_by_id.get(pid, pid)))
        else:
            pairs = sorted(
                ((pid, name_by_id.get(pid, pid)) for pid in roster if pid in available),
                key=lambda x: x[0],
            )
        return pairs[: self.clamp(max_employees)]

    def recent_failures(self, employee_id: str, limit: int = 6) -> List[Dict[str, Any]]:
        """读员工最近真实失败/告警的执行流水，给"问题与解决"段落做事实根基。

        只纳入真正的失败状态（``failed``、``error``，以及有非空 error 字段的 ``success``）；
        排除 ``skipped``、``blocked_by_risk_gate``、``warning`` 等正常/预期状态。
        默认只取最近 72h 内的记录（可通过 ``MODSTORE_RECENT_FAILURES_HOURS`` 覆盖）。
        同一 ``(task 前缀, error 前缀)`` 组合去重，避免重复 craft 步骤生成多张 P0 卡。
        """
        import os

        hours = int(os.environ.get("MODSTORE_RECENT_FAILURES_HOURS") or 72)
        sf = self.session_provider()
        out: List[Dict[str, Any]] = []
        seen_keys: set = set()
        with sf() as session:
            cutoff: Optional[datetime] = None
            if hours > 0:
                from datetime import timedelta

                cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                    hours=hours
                )
            q = session.query(EmployeeExecutionMetric).filter(
                EmployeeExecutionMetric.employee_id == employee_id
            )
            if cutoff is not None:
                q = q.filter(cast(Any, EmployeeExecutionMetric.created_at) >= cutoff)
            metric_rows = q.order_by(desc(EmployeeExecutionMetric.id)).limit(120).all()
            for r in metric_rows:
                status = str(getattr(r, "status", "") or "")
                err = (getattr(r, "error", "") or "").strip()
                is_real_failure = status in ("failed", "error")
                is_success_with_err = status == "success" and bool(err)
                if not (is_real_failure or is_success_with_err):
                    continue
                task_key = str(r.task or "")[:60]
                err_key = err[:80]
                dedup = (task_key, err_key)
                if dedup in seen_keys:
                    continue
                seen_keys.add(dedup)
                out.append(
                    {
                        "id": int(r.id),
                        "task": str(r.task or "")[:160],
                        "status": status,
                        "duration_ms": float(r.duration_ms or 0.0),
                        "llm_tokens": int(r.llm_tokens or 0),
                        "error": err[:600],
                        "created_at": (
                            r.created_at.replace(tzinfo=timezone.utc).isoformat()
                            if isinstance(r.created_at, datetime)
                            and r.created_at.tzinfo is None
                            else r.created_at.isoformat()
                            if r.created_at
                            else None
                        ),
                    }
                )
                if len(out) >= limit:
                    break
        return out

    def pending_changes(self, limit: int = 12) -> List[Dict[str, Any]]:
        from modstore_server.models import EmployeeChangeRequest

        out: List[Dict[str, Any]] = []
        try:
            sf = self.session_provider()
            with sf() as session:
                rows = (
                    session.query(EmployeeChangeRequest)
                    .filter(EmployeeChangeRequest.status == "pending")
                    .order_by(desc(EmployeeChangeRequest.id))
                    .limit(max(1, min(limit, 30)))
                    .all()
                )
                for r in rows:
                    out.append(
                        {
                            "id": int(r.id),
                            "source_employee_id": str(r.source_employee_id or ""),
                            "change_kind": str(r.change_kind or ""),
                            "risk_level": str(r.risk_level or ""),
                            "status": str(r.status or ""),
                            "diff_summary": str(r.diff_summary or "")[:400],
                            "target_paths": (
                                json.loads(str(r.target_paths_json or "[]"))[:6]
                                if str(r.target_paths_json or "")
                                .strip()
                                .startswith("[")
                                else []
                            ),
                            "git_branch": str(r.git_branch or "")[:120],
                            "created_at": r.created_at.isoformat()
                            if r.created_at
                            else None,
                        }
                    )
        except RECOVERABLE_ERRORS as exc:
            logger.debug("all_hands: pending change requests snapshot failed: %s", exc)
        return out
