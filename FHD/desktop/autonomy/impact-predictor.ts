/**
 * Impact Predictor：运行时预检门禁
 *
 * 用户决策：运行时预检 + Policy 门禁（不做静态依赖图）。
 * 所有动作执行前必须通过 predict()，allow=false 时写 audit 不执行。
 *
 * 设计：拦截不阻断。误判仅记录，不抛错。
 */

import type { Action, RuntimeTruthSnapshot } from './types.js'

export interface Prediction {
  allow: boolean
  reasons: string[]
  suggestions?: string[]
}

/** 7 天毫秒数，用于回滚前检查备份新鲜度 */
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000

/** backend 启动后最小观察期 10 秒，避免误重启 */
const BACKEND_INIT_GUARD_MS = 10_000

/** 磁盘清理触发阈值 */
const DISK_CLEAN_THRESHOLD = 70

/**
 * 预测动作的副作用风险
 * @param action 待执行动作
 * @param truth 当前现实快照
 * @returns allow=true 可执行；allow=false 必须记录 reasons 并跳过
 */
export function predict(action: Action, truth: RuntimeTruthSnapshot): Prediction {
  const reasons: string[] = []
  const suggestions: string[] = []
  const now = Date.now()

  switch (action.type) {
    case 'restart_backend': {
      // 风险：backend 正在初始化时重启会浪费启动周期
      if (truth.backend?.running && truth.backend.startedAt && now - truth.backend.startedAt < BACKEND_INIT_GUARD_MS) {
        reasons.push(`backend 启动不足 ${BACKEND_INIT_GUARD_MS / 1000}s（${Math.round((now - truth.backend.startedAt) / 1000)}s），可能正在初始化，避免误重启`)
      }
      // 风险：端口未占用说明 backend 已退出，restart 无意义
      if (!truth.port_in_use) {
        reasons.push('端口未占用，backend 可能已退出，应直接 spawn 而非 restart')
      }
      // 风险：最近已重启多次
      if (truth.restart_count >= 3) {
        reasons.push(`restart_count=${truth.restart_count} 已达上限，继续重启可能徒劳`)
        suggestions.push('考虑 rollback_version 或 escalate')
      }
      break
    }
    case 'rollback_version': {
      // 风险：嵌套回滚（已有 pending marker）
      if (truth.pending_rollback_marker) {
        reasons.push('已存在 rollback marker，禁止嵌套回滚')
      }
      // 风险：备份过旧，回滚后数据丢失
      if (truth.last_backup_ts !== null && now - truth.last_backup_ts > SEVEN_DAYS_MS) {
        reasons.push(`最近备份超过 7 天（${Math.round((now - truth.last_backup_ts) / (24 * 3600 * 1000))} 天前），回滚后数据可能丢失`)
        suggestions.push('先执行手动备份再回滚')
      }
      if (truth.last_backup_ts === null) {
        reasons.push('无已知备份，回滚后无数据可恢复')
      }
      break
    }
    case 'clear_cache': {
      // 风险：磁盘未紧张时清理无意义（且可能误删用户临时文件）
      if (truth.disk_usage_percent < DISK_CLEAN_THRESHOLD) {
        reasons.push(`磁盘占用 ${truth.disk_usage_percent}% < 阈值 ${DISK_CLEAN_THRESHOLD}%，无需清理`)
      }
      break
    }
    case 'repair_config': {
      // 风险：配置未漂移时"修复"反而引入漂移
      if (!truth.config_fingerprint_changed) {
        reasons.push('配置未漂移，无需修复')
      }
      break
    }
    case 'restart_service':
    case 'rollback_to_last_tarball':
    case 'freeze_manifest':
    case 'clear_logs':
    case 'escalate':
    case 'noop':
      // 服务器端动作在桌面端不预检；服务器端 cvm_adapter 自行预检
      break
  }

  return {
    allow: reasons.length === 0,
    reasons,
    ...(suggestions.length > 0 ? { suggestions } : {}),
  }
}
