"""自治平台核心类型契约（与桌面端 FHD/desktop/autonomy/types.ts 字段对称）。

设计原则：
  - 与层级无关：不依赖任何运行时（仅 Python 3.11 标准库）
  - Policy 为纯函数：plan(signals) 必须可重复执行（禁止 time.time() / datetime.now()）
  - 所有动作可审计：AuditEntry 是唯一事后真相
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol, TypedDict

# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class ActionType(str, Enum):
    """动作类型枚举（三端共用；服务器端 8 个 + 桌面端 4 个）。

    服务器端实际使用：restart_service / rollback_to_last_tarball / freeze_manifest
    / unfreeze_manifest / clear_logs / escalate / noop / open_incident_issue
    """

    RESTART_BACKEND = "restart_backend"
    ROLLBACK_VERSION = "rollback_version"
    CLEAR_CACHE = "clear_cache"
    REPAIR_CONFIG = "repair_config"
    RESTART_SERVICE = "restart_service"
    ROLLBACK_TO_LAST_TARBALL = "rollback_to_last_tarball"
    FREEZE_MANIFEST = "freeze_manifest"
    UNFREEZE_MANIFEST = "unfreeze_manifest"
    CLEAR_LOGS = "clear_logs"
    ESCALATE = "escalate"
    NOOP = "noop"
    OPEN_INCIDENT_ISSUE = "open_incident_issue"


class RiskLevel(str, Enum):
    """动作风险分级（决定 auto / cooldown / escalate）。

    - low: 自动执行（freeze_manifest / clear_logs / noop）
    - medium: 自动执行 + cooldown 5min（restart_service）
    - high: 不自动执行，仅 escalate（rollback_to_last_tarball）
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --------------------------------------------------------------------------- #
# 七元契约
# --------------------------------------------------------------------------- #


class SignalPayload(TypedDict, total=False):
    """Signal.payload 的结构化负载（任意键值，可空）。"""

    code: str
    uptime: float
    path: str
    percent: float
    reason: str


@dataclass
class Signal:
    """信号：自治系统的输入事件。

    与桌面端 types.ts Signal 字段对称。
    Policy 用 ``ts`` 字段计算时间窗口，禁止用 time.time() / datetime.now()。
    """

    source: str
    kind: str
    severity: Literal["info", "warn", "crit", "fatal"]
    detail: str
    ts: int  # UNIX 毫秒时间戳
    payload: dict[str, Any] | None = None


@dataclass
class Diagnosis:
    """诊断结果：根因分析输出。"""

    root_cause: str
    confidence: float  # 0..1
    detail: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Action:
    """动作：Policy 决策的输出，由 Adapter 执行。

    - idempotency_key: 相同 key 在 cooldown 窗口内不重复执行
    - max_attempts: 耗尽后转 escalate
    - risk: high 默认需 escalate；low/medium 自动执行
    """

    type: ActionType
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    max_attempts: int = 1
    risk: RiskLevel = RiskLevel.LOW


@dataclass
class ActionResult:
    """动作执行结果。"""

    action: Action
    ok: bool
    detail: str
    ts: int  # UNIX 毫秒时间戳


@dataclass
class Plan:
    """Policy 决策输出：诊断 + 动作列表。"""

    diagnosis: Diagnosis
    actions: list[Action] = field(default_factory=list)


class Policy(Protocol):
    """Policy：信号 → 决策的纯函数接口。

    实现必须满足：
      1. plan(signals) 禁止 time.time() / datetime.now()，时间窗口用 signals 自身 ts
      2. 相同输入信号产出相同决策（可重复执行，便于回放与测试）
      3. matches 字段声明匹配的 signal kind
    """

    id: str
    matches: list[str]
    gate: Literal["auto", "approve", "manual"]

    def plan(self, signals: list[Signal]) -> Plan:
        """根据信号列表输出诊断与动作。"""
        ...


@dataclass
class RuntimeTruthSnapshot:
    """RuntimeTruthSnapshot：决策时的现实快照（impact-predictor 的输入）。

    与桌面端 types.ts RuntimeTruthSnapshot 字段对称；
    服务器端独有字段（deploy_root / manifest_path / compose_status / health_ok /
    service_running / pending_rollback_marker）。
    """

    ts: int  # 采集时间戳（UNIX ms）
    # 服务器端独有：部署相关
    deploy_root: str
    manifest_path: str
    compose_status: str  # 'running' | 'exited' | 'absent' | 'unknown'
    health_ok: bool  # /api/health 探测结果
    service_running: bool  # docker compose ps 是否有 running 服务
    pending_rollback_marker: bool  # 是否存在 pending rollback marker
    # 与桌面端共用
    disk_usage_percent: float  # 0..100
    config_fingerprint_changed: bool  # 服务器端常为 False（不跟踪配置）
    last_backup_ts: int | None  # .deploy-last.tar.gz mtime
    app_version: str
    build_sha: str
    restart_count: int = 0  # 服务器端常为 0（不跟踪重启计数）
    # manifest 状态
    manifest_exists: bool = True
    manifest_frozen: bool = False  # .frozen marker 文件是否存在
    # 自定义扩展字段
    extra: dict[str, Any] | None = None


@dataclass
class AuditEntry:
    """审计条目：所有动作必须记录（含 skipped）。

    与桌面端 types.ts AuditEntry 字段对称。
    audit.jsonl 每行一个 JSON 对象。
    """

    ts: str  # UTC ISO 时间戳
    source_signal: Signal | None
    diagnosis: Diagnosis | None
    action: Action | dict[str, Any] | None  # skipped 时为 {type: 'skipped', reasons: [...]}
    result: ActionResult | None
    truth_snapshot: RuntimeTruthSnapshot | None = None


# --------------------------------------------------------------------------- #
# Adapter 接口（与桌面端 AutonomyAdapter 对称）
# --------------------------------------------------------------------------- #


class AutonomyAdapter(Protocol):
    """AutonomyAdapter：层级无关的执行接口。

    服务器端实现见 cvm_adapter.CvmAutonomyAdapter。
    """

    def collect_truth(self) -> RuntimeTruthSnapshot:
        """采集运行时现实快照。"""
        ...

    def subscribe_signals(self, emit: Any) -> None:
        """订阅信号。服务器端无主动信号（由 watcher tick 派生）。"""
        ...

    def execute_action(self, action: Action) -> ActionResult:
        """执行动作。"""
        ...

    def audit(self, entry: AuditEntry) -> None:
        """写审计条目（同步、不抛错）。"""
        ...


# --------------------------------------------------------------------------- #
# ImpactPredictor 输出
# --------------------------------------------------------------------------- #


@dataclass
class Prediction:
    """预测动作的副作用风险。

    allow=False 时 controller 不执行 action，写 audit skipped。
    reasons 解释拒绝原因；suggestions 提供替代动作建议。
    """

    allow: bool
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 控制器配置（与桌面端 ControllerOptions 对称）
# --------------------------------------------------------------------------- #


@dataclass
class ControllerOptions:
    """控制器选项。"""

    enabled: bool = True
    poll_interval_ms: int = 5_000
    signal_retention_ms: int = 30 * 60 * 1000  # 30 分钟
    default_cooldown_ms: int = 5 * 60 * 1000  # 5 分钟


# --------------------------------------------------------------------------- #
# 动作执行追踪
# --------------------------------------------------------------------------- #


@dataclass
class ActionTracker:
    """内部动作执行追踪（与桌面端 controller.ts ActionTracker 对称）。

    用于 cooldown + max_attempts + escalate 守护链。
    """

    idempotency_key: str
    attempts: int = 0
    last_attempt_ts: int = 0
    escalated: bool = False
