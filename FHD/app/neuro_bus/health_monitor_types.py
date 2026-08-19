"""Value objects and fixed receipt codes for health monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """健康状态"""

    HEALTHY = "healthy"  # 健康
    DEGRADED = "degraded"  # 降级
    UNHEALTHY = "unhealthy"  # 不健康
    UNKNOWN = "unknown"  # 未知


class AlertLevel(Enum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    component: str
    status: HealthStatus
    message: str
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)


# ========== 闭环自愈（safe remediation closed loop） ==========

# 结构化接收单（event_type）—— 全部为固定字符串，不携带任意数据
INCIDENT_REPORTED = "health.incident.reported"
REMEDIATION_REPORTED = "health.remediation.reported"
REMEDIATION_FAILED = "health.remediation.failed"
REMEDIATION_SKIPPED = "health.remediation.skipped"
RECOVERY_REPORTED = "health.recovery.reported"
RECOVERY_FAILED = "health.recovery.failed"

# 固定原因码 —— 绝不写入 result.details / 异常文本 / 命令 / URL / token 等任意字符串
REASON_NOT_REGISTERED = "remediation_not_registered"
REASON_REMEDIATION_FAILED = "remediation_failed"
REASON_POSTCONDITION_UNHEALTHY = "postcondition_unhealthy"
REASON_EVENT_STORE_UNAVAILABLE = "event_store_unavailable"

# 固定状态码
STATUS_EVIDENCE_UNAVAILABLE = "evidence_unavailable"

# 组件修复处理器：仅接收结构化 HealthCheckResult，同步或异步均可
RemediationHandler = Callable[[HealthCheckResult], Any]


@dataclass
class RemediationOutcome:
    """闭环自愈结果（安全、结构化、无任意字符串）"""

    component: str
    status: str  # healthy | remediation_skipped | remediation_failed | already_attempted | recovered | recovery_failed | evidence_unavailable
    incident_id: str | None
    action_id: str | None
    reason_code: str | None
    handler_invoked: bool
    recovered: bool
    durable_receipts: bool
    stream_id: str | None


@dataclass
class Alert:
    """告警"""

    alert_id: str
    level: AlertLevel
    component: str
    message: str
    created_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
