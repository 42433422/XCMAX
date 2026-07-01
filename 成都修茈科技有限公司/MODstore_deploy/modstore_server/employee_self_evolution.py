"""员工自进化信号（10 项成熟度第 9 项「会学习」）。

失败 3 次以后不能继续重复失败，要改自己的 runbook、提示词、检查清单，
或者升级给更合适的员工。

本模块只做「检测 + 信号」：
  - 查最近 N 小时同员工失败次数
  - 如果 >=3 次，返回 evolution_signal={needed:True, ...}
  - 调用方（employee_executor）把信号写到 result["evolution_signal"]
  - human_report 反映：⚠️ 该员工最近失败 X 次，建议运行 prompt evolution

实际触发 prompt evolution 的工作由 employee_autonomy_service.run_employee_evolution_scan
+ admin API /api/admin/employee-autonomy/evolution/scan 完成，本模块不重复实现。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_HOURS = 24
_DEFAULT_MIN_FAILURES = 3


def check_evolution_signal(
    *,
    employee_id: str,
    session,
    lookback_hours: int = _DEFAULT_LOOKBACK_HOURS,
    min_failures: int = _DEFAULT_MIN_FAILURES,
) -> Dict[str, Any]:
    """检查员工最近 N 小时失败次数，决定是否需要触发 prompt evolution。

    返回：
      {
        "needed": bool,             # 是否需要进化
        "fail_count": int,           # 失败次数
        "min_failures": int,         # 阈值
        "lookback_hours": int,       # 回溯窗口
        "suggestion": str,           # 给老板的建议
        "recent_failures": [...],    # 最近失败任务摘要（最多 3 条）
        "evolution_api": str,        # 调用的 API endpoint
      }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(lookback_hours))
    try:
        from modstore_server.models_user import EmployeeExecutionMetric
    except ImportError:
        return {
            "needed": False,
            "fail_count": 0,
            "reason": "EmployeeExecutionMetric 表不可用",
        }
    try:
        rows = (
            session.query(EmployeeExecutionMetric)
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.created_at >= cutoff,
                EmployeeExecutionMetric.status != "success",
            )
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(20)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("evolution_signal query failed employee_id=%s err=%s", employee_id, exc)
        return {
            "needed": False,
            "fail_count": 0,
            "error": str(exc)[:200],
        }

    fail_count = len(rows)
    needed = fail_count >= int(min_failures)
    recent_failures = []
    for r in rows[:3]:
        recent_failures.append(
            {
                "task": (r.task or "")[:120],
                "status": str(r.status or ""),
                "failure_kind": str(r.failure_kind or ""),
                "error_preview": (
                    (r.error_preview or "")[:150] if hasattr(r, "error_preview") else ""
                ),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )

    if needed:
        suggestion = (
            f"该员工最近 {lookback_hours} 小时失败 {fail_count} 次（>= 阈值 {min_failures}），"
            "建议运行 prompt evolution：调用 admin API 触发 LLM 自改 system_prompt + A/B 验证。"
        )
    else:
        suggestion = (
            f"该员工最近 {lookback_hours} 小时失败 {fail_count} 次（< 阈值 {min_failures}），"
            "暂不需要 prompt evolution。"
        )

    return {
        "needed": needed,
        "fail_count": fail_count,
        "min_failures": int(min_failures),
        "lookback_hours": int(lookback_hours),
        "suggestion": suggestion,
        "recent_failures": recent_failures,
        "evolution_api": "POST /api/admin/employee-autonomy/evolution/scan",
    }


__all__ = ["check_evolution_signal"]
