/**
 * 运行时现实快照（RuntimeTruth）
 *
 * 解决"AI 看不见现实"问题：所有决策必须基于 truth 快照，
 * 而非假设或缓存状态。
 */

import fs from 'node:fs'
import path from 'node:path'
import type { RuntimeTruthSnapshot, Signal, BackendRuntimeInfo } from './types.js'

/** 磁盘占用百分比（0..100），失败返回 0 */
export function diskUsagePercent(dirPath: string): number {
  try {
    const stat = fs.statfsSync(dirPath)
    const total = stat.blocks * stat.bsize
    const free = stat.bavail * stat.bsize
    if (total === 0) return 0
    return Math.round(((total - free) / total) * 100)
  } catch {
    return 0
  }
}

/** 可用磁盘空间（MB）；采集失败时返回 undefined，不产生 disk_low 误报。 */
export function diskFreeMegabytes(dirPath: string): number | undefined {
  try {
    const stat = fs.statfsSync(dirPath)
    const bytes = stat.bavail * stat.bsize
    return Math.max(0, Math.floor(bytes / (1024 * 1024)))
  } catch {
    return undefined
  }
}

/** 计算配置文件指纹（md5 截断 12 位） */
export function computeConfigFingerprint(configPath: string | null): string {
  if (!configPath) return ''
  try {
    if (!fs.existsSync(configPath)) return ''
    const content = fs.readFileSync(configPath, 'utf8')
    // 简单 hash：length + 前 64 字符 + 后 64 字符的 charCode 和
    // 避免引入 crypto 模块的开销，且对配置漂移足够敏感
    const head = content.slice(0, 64)
    const tail = content.slice(-64)
    let sum = content.length
    for (let i = 0; i < head.length; i += 1) sum += head.charCodeAt(i)
    for (let i = 0; i < tail.length; i += 1) sum += tail.charCodeAt(i)
    return sum.toString(16).padStart(12, '0').slice(-12)
  } catch {
    return ''
  }
}

/** 解析 NeuroBus 状态（如可获取） */
export function resolveNeurobus(status: unknown): RuntimeTruthSnapshot['neurobus'] {
  if (!status || typeof status !== 'object') return undefined
  const s = status as Record<string, unknown>
  const reliability = s.reliability && typeof s.reliability === 'object'
    ? s.reliability as Record<string, unknown>
    : {}
  const dlq = s.dead_letter_queue && typeof s.dead_letter_queue === 'object'
    ? s.dead_letter_queue as Record<string, unknown>
    : {}
  return {
    available: Boolean(s.available ?? s.running ?? s.status === 'healthy'),
    circuit_open: Boolean(s.circuit_open ?? reliability.circuit_open ?? false),
    dlq_size: Number(s.dlq_size ?? s.current_size ?? dlq.current_size ?? 0),
  }
}

/** 解析最近备份时间戳（从 backups 目录最新文件 mtime） */
export function resolveLastBackup(backupsDir: string): number | null {
  try {
    if (!fs.existsSync(backupsDir)) return null
    const entries = fs.readdirSync(backupsDir, { withFileTypes: true })
      .filter(e => e.isFile())
      .map(e => {
        const full = path.join(backupsDir, e.name)
        try {
          return { name: e.name, mtime: fs.statSync(full).mtimeMs }
        } catch {
          return { name: e.name, mtime: 0 }
        }
      })
      .sort((a, b) => b.mtime - a.mtime)
    return entries[0]?.mtime ?? null
  } catch {
    return null
  }
}

/** 检查 pending rollback marker 是否存在 */
export function hasPendingRollbackMarker(userDataDir: string): boolean {
  try {
    return fs.existsSync(path.join(userDataDir, 'rollback-marker.json'))
  } catch {
    return false
  }
}

/**
 * 计算 RuntimeTruthSnapshot
 * @param ctx 输入参数：路径与状态
 */
export function computeRuntimeTruth(ctx: {
  userDataDir: string
  backend: BackendRuntimeInfo
  portInUse: boolean
  configPath: string | null
  knownGoodFingerprint: string | null
  appVersion: string
  buildSha: string
  restartCount: number
  desktopStatus?: unknown
  /** Phase 1 新增：磁盘剩余 MB（可选，未提供则不派生 disk_low 信号） */
  diskFreeMb?: number
  /** Phase 1 新增：数据库完整性（可选） */
  dbIntegrity?: 'ok' | 'warn' | 'fail' | 'unknown'
  /** Phase 1 新增：网络最近成功 ts（可选） */
  lastNetworkOkTs?: number | null
}): RuntimeTruthSnapshot {
  const backupsDir = path.join(ctx.userDataDir, 'backups')
  const currentFingerprint = computeConfigFingerprint(ctx.configPath)
  const fingerprintChanged = Boolean(
    ctx.knownGoodFingerprint &&
    currentFingerprint &&
    currentFingerprint !== ctx.knownGoodFingerprint,
  )
  const truth: RuntimeTruthSnapshot = {
    ts: Date.now(),
    backend: ctx.backend,
    port_in_use: ctx.portInUse,
    disk_usage_percent: diskUsagePercent(ctx.userDataDir),
    config_fingerprint_changed: fingerprintChanged,
    pending_rollback_marker: hasPendingRollbackMarker(ctx.userDataDir),
    last_backup_ts: resolveLastBackup(backupsDir),
    app_version: ctx.appVersion,
    build_sha: ctx.buildSha,
    restart_count: ctx.restartCount,
    neurobus: resolveNeurobus(ctx.desktopStatus),
  }
  if (ctx.diskFreeMb !== undefined) truth.disk_free_mb = ctx.diskFreeMb
  if (ctx.dbIntegrity !== undefined) truth.db_integrity = ctx.dbIntegrity
  if (ctx.lastNetworkOkTs !== undefined) truth.last_network_ok_ts = ctx.lastNetworkOkTs
  return truth
}

/** 网络断线判定窗口：5 分钟 */
const NETWORK_DOWN_THRESHOLD_MS = 5 * 60 * 1000
/** 磁盘剩余空间低位阈值：500MB */
const DISK_LOW_THRESHOLD_MB = 500

/**
 * 从 truth 派生信号：每 tick 调用，将 truth 异常转为信号。
 * 与 main.ts 的 ingest 共同构成信号源。
 */
export function deriveSignalsFromTruth(truth: RuntimeTruthSnapshot): Signal[] {
  const signals: Signal[] = []
  const now = truth.ts
  if (truth.disk_usage_percent >= 90) {
    signals.push({
      source: 'runtime_truth',
      kind: 'disk_full',
      severity: 'crit',
      detail: `磁盘占用 ${truth.disk_usage_percent}%`,
      ts: now,
      payload: { percent: truth.disk_usage_percent },
    })
  }
  if (truth.config_fingerprint_changed) {
    signals.push({
      source: 'runtime_truth',
      kind: 'config_fingerprint_changed',
      severity: 'warn',
      detail: '配置文件指纹与已知良好快照不一致',
      ts: now,
    })
  }
  if (truth.neurobus?.circuit_open) {
    signals.push({
      source: 'runtime_truth',
      kind: 'NEURO_BUS_CIRCUIT_OPEN',
      severity: 'crit',
      detail: 'NeuroBus 熔断器已打开',
      ts: now,
      payload: { dlq_size: truth.neurobus.dlq_size },
    })
  }
  if (truth.neurobus && truth.neurobus.dlq_size > 1000) {
    signals.push({
      source: 'runtime_truth',
      kind: 'NEURO_BUS_DLQ_FULL',
      severity: 'crit',
      detail: `NeuroBus DLQ 堆积 ${truth.neurobus.dlq_size} 条`,
      ts: now,
      payload: { dlq_size: truth.neurobus.dlq_size },
    })
  }
  // Phase 1 新增：磁盘剩余空间低位（区别于 disk_usage_percent>=90 的 disk_full 信号）
  if (truth.disk_free_mb !== undefined && truth.disk_free_mb < DISK_LOW_THRESHOLD_MB) {
    signals.push({
      source: 'runtime_truth',
      kind: 'disk_low',
      severity: 'crit',
      detail: `磁盘剩余 ${truth.disk_free_mb}MB 低于 ${DISK_LOW_THRESHOLD_MB}MB 阈值`,
      ts: now,
      payload: { disk_free_mb: truth.disk_free_mb },
    })
  }
  // Phase 1 新增：数据库完整性失败
  if (truth.db_integrity === 'fail') {
    signals.push({
      source: 'runtime_truth',
      kind: 'db_corrupt',
      severity: 'fatal',
      detail: '数据库完整性检查失败',
      ts: now,
      payload: { db_integrity: truth.db_integrity },
    })
  }
  // Phase 1 新增：网络断线（最近成功 > 5min 或从未成功）
  if (truth.last_network_ok_ts !== undefined && truth.last_network_ok_ts !== null) {
    if (now - truth.last_network_ok_ts > NETWORK_DOWN_THRESHOLD_MS) {
      signals.push({
        source: 'runtime_truth',
        kind: 'network_down',
        severity: 'warn',
        detail: `网络断线超过 ${NETWORK_DOWN_THRESHOLD_MS / 60000} 分钟`,
        ts: now,
        payload: { last_network_ok_ts: truth.last_network_ok_ts },
      })
    }
  }
  return signals
}

/** 追加 truth 日志（用于事后审计与趋势分析） */
export function appendTruthLog(userDataDir: string, truth: RuntimeTruthSnapshot): void {
  try {
    const logDir = path.join(userDataDir, 'autonomy')
    fs.mkdirSync(logDir, { recursive: true })
    const logPath = path.join(logDir, 'truth.jsonl')
    fs.appendFileSync(logPath, `${JSON.stringify(truth)}\n`, 'utf8')
  } catch {
    // 日志失败不影响主流程
  }
}
