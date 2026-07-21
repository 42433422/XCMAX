/**
 * 自治平台核心类型契约（三端共用：桌面 / 服务器 / CI）
 *
 * 设计原则：
 * - 与层级无关：不依赖 electron / node / browser 任何运行时
 * - Policy 为纯函数：plan(signals) 必须可重复执行
 * - 所有动作可审计：AuditEntry 是唯一事后真相
 */

/** 信号：自治系统的输入事件 */
export interface Signal {
  /** 信号来源标识（如 'backend_exit' / 'health_check' / 'ci_failed'） */
  source: string
  /** 信号类型，用于 Policy.matches 匹配（如 'backend_exit' / 'disk_full'） */
  kind: string
  /** 严重程度：info / warn / crit / fatal */
  severity: 'info' | 'warn' | 'crit' | 'fatal'
  /** 人类可读描述 */
  detail: string
  /** UNIX 毫秒时间戳（Policy 用此字段计算窗口，禁止用 Date.now()） */
  ts: number
  /** 任意结构化负载（code / uptime / path 等） */
  payload?: Record<string, unknown>
}

/** 诊断结果：根因分析输出 */
export interface Diagnosis {
  /** 根因标识（与 RCA_MAP key 一致） */
  root_cause: string
  /** 置信度 0..1 */
  confidence: number
  /** 人类可读诊断详情 */
  detail: string
  /** 支撑诊断的证据片段（日志行 / 指标值 / 文件路径） */
  evidence: string[]
}

/** 动作类型枚举（三端共用，未列出的动作视为 unknown） */
export type ActionType =
  | 'restart_backend'
  | 'rollback_version'
  | 'clear_cache'
  | 'repair_config'
  | 'restart_service'
  | 'rollback_to_last_tarball'
  | 'freeze_manifest'
  | 'clear_logs'
  | 'escalate'
  | 'noop'

/** 动作风险分级（决定自动执行 / escalate） */
export type RiskLevel = 'low' | 'medium' | 'high'

/** 动作：Policy 决策的输出，由 Adapter 执行 */
export interface Action {
  type: ActionType
  /** 动作参数（如 reason / target_path / version） */
  params: Record<string, unknown>
  /** 幂等键：相同 key 在 cooldown 窗口内不重复执行 */
  idempotency_key: string
  /** 最大尝试次数：耗尽后转 escalate */
  max_attempts: number
  /** 风险等级：high 默认需 escalate，low/medium 自动执行 */
  risk: RiskLevel
}

/** 动作执行结果 */
export interface ActionResult {
  action: Action
  ok: boolean
  detail: string
  ts: number
}

/** Policy 决策输出 */
export interface Plan {
  diagnosis: Diagnosis
  actions: Action[]
}

/** Policy：信号 → 决策的纯函数 */
export interface Policy {
  /** Policy 唯一标识 */
  id: string
  /** 匹配的 signal kind 列表 */
  matches: string[]
  /** 决策门禁：'auto' 自动执行 / 'approve' 需人审批 / 'manual' 仅建议 */
  gate: 'auto' | 'approve' | 'manual'
  /** 纯函数：根据信号列表输出诊断与动作。**禁止调用 Date.now()**，时间窗口用 signals 自身 ts */
  plan: (signals: Signal[]) => Plan
}

/** 后端运行态快照 */
export interface BackendRuntimeInfo {
  pid: number | null
  running: boolean
  startedAt: number | null
}

/** RuntimeTruthSnapshot：决策时的现实快照（impact-predictor 的输入） */
export interface RuntimeTruthSnapshot {
  /** 采集时间戳 */
  ts: number
  /** 后端进程信息 */
  backend: BackendRuntimeInfo
  /** 端口是否被占用 */
  port_in_use: boolean
  /** 磁盘占用百分比 0..100 */
  disk_usage_percent: number
  /** 配置文件指纹是否变化 */
  config_fingerprint_changed: boolean
  /** 是否存在 pending rollback marker（避免嵌套回滚） */
  pending_rollback_marker: boolean
  /** 最近一次备份时间戳（用于回滚前检查） */
  last_backup_ts: number | null
  /** 应用版本 */
  app_version: string
  /** 构建 SHA */
  build_sha: string
  /** 重启计数 */
  restart_count: number
  /** NeuroBus 状态（如可获取） */
  neurobus?: {
    available: boolean
    circuit_open: boolean
    dlq_size: number
  }
  /** Phase 1 新增：磁盘剩余 MB（< 500 派生 disk_low 信号） */
  disk_free_mb?: number
  /** Phase 1 新增：数据库完整性检查结果（'fail' 派生 db_corrupt 信号） */
  db_integrity?: 'ok' | 'warn' | 'fail' | 'unknown'
  /** Phase 1 新增：网络连通性（外网 API 探测，最近一次成功 ts；超过 5min 派生 network_down） */
  last_network_ok_ts?: number | null
  /** 自定义扩展字段（服务器/CI 端可补充） */
  extra?: Record<string, unknown>
}

/** 审计条目：所有动作必须记录 */
export interface AuditEntry {
  /** UTC ISO 时间戳 */
  ts: string
  /** 触发动作的信号（如无动作则为 null） */
  source_signal: Signal | null
  /** 诊断结果 */
  diagnosis: Diagnosis | null
  /** 动作（skipped 时仍记录） */
  action: Action | { type: 'skipped'; reasons: string[] } | null
  /** 执行结果 */
  result: ActionResult | null
  /** 触发时的 truth 快照（可裁剪） */
  truth_snapshot?: Partial<RuntimeTruthSnapshot>
}

/**
 * AutonomyAdapter：层级无关的执行接口。
 * 桌面/服务器/CI 各自实现，控制器只依赖此接口。
 */
export interface AutonomyAdapter {
  /** 采集运行时现实快照 */
  collectTruth(): Promise<RuntimeTruthSnapshot>
  /** 订阅信号（适配器可主动 push，控制器也可轮询 truth 派生） */
  subscribeSignals(emit: (signal: Signal) => void): void
  /** 执行动作 */
  executeAction(action: Action): Promise<ActionResult>
  /** 写审计条目（同步、不抛错） */
  audit(entry: AuditEntry): void
  /** Phase 4 新增：跨端门禁查询其他端状态。未实现 / 抛错 → fail-closed（阻断） */
  getRemoteState?(): Promise<Record<string, unknown> | null>
}

/** 控制器选项 */
export interface ControllerOptions {
  /** 是否启用（false 时 tick 直接返回） */
  enabled?: boolean
  /** 轮询间隔毫秒，默认 5000 */
  pollIntervalMs?: number
  /** 信号保留窗口毫秒，默认 30 分钟 */
  signalRetentionMs?: number
  /** cooldown 默认窗口毫秒，默认 5 分钟 */
  defaultCooldownMs?: number
}
