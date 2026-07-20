"""服务器端 Policy 集合（Phase 2）。

4 个 Policy：
  - health_down_policy: health_down → restart_service（medium + cooldown 5min）
  - manifest_drift_policy: manifest_drift → freeze_manifest（low）
  - disk_full_policy: disk_full → clear_logs（low，max_attempts=2）
  - compose_unhealthy_policy: compose_unhealthy → restart_service（medium + cooldown 5min）

设计原则（与桌面端 policies/*.policy.ts 一致）：
  - 纯函数：plan(signals) 禁止 time.time() / datetime.now()，时间窗口用 signals 自身 ts
  - latest signal ts 作 "now"（与桌面端 backend-crash.policy 一致）
  - 按 kind 去重：每 kind 只取最新一条信号（与桌面端 degraded-remediation.policy 一致）
  - max_attempts 耗尽后 controller 转 escalate（不在此处实现，由 watcher 守护链处理）
"""

from __future__ import annotations

from .disk_full_policy import disk_full_policy
from .health_down_policy import health_down_policy
from .manifest_drift_policy import manifest_drift_policy
from .compose_unhealthy_policy import compose_unhealthy_policy

# 导出所有 Policy（供 watcher 使用）
ALL_POLICIES = [
    health_down_policy,
    manifest_drift_policy,
    disk_full_policy,
    compose_unhealthy_policy,
]

__all__ = [
    "ALL_POLICIES",
    "health_down_policy",
    "manifest_drift_policy",
    "disk_full_policy",
    "compose_unhealthy_policy",
]
