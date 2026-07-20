/**
 * Policy：OTA 更新失败自动回滚（预留）
 *
 * 触发：ota_install_failed 信号
 * 决策：rollback_version（high 风险，max_attempts=1）
 *
 * 当前 main.ts 未发该信号，本 policy 为未来迁移预留。
 * 现有 main.ts 的 5 秒观察期 + checkPendingRollback 已覆盖 OTA 失败回滚。
 */

import type { Policy, Signal, Action, Diagnosis } from '../types.js'
import { diagnoseRootCause } from '../rca-rules.js'

export const updateRollbackPolicy: Policy = {
  id: 'update-rollback',
  matches: ['ota_install_failed'],
  gate: 'auto',
  plan(signals: Signal[]): { diagnosis: Diagnosis; actions: Action[] } {
    const diagnosis = diagnoseRootCause(signals)
    const fails = signals.filter(s => s.kind === 'ota_install_failed')
    if (fails.length === 0) return { diagnosis, actions: [] }
    // 取最新失败信号提取 reason
    const latest = fails.sort((a, b) => b.ts - a.ts)[0]
    const reason = String(latest.payload?.reason || latest.detail || 'OTA 安装失败')
    return {
      diagnosis,
      actions: [
        {
          type: 'rollback_version',
          params: { reason, source: 'ota_install_failed', signal_ts: latest.ts },
          idempotency_key: 'rollback:ota-install-failed',
          max_attempts: 1,
          risk: 'high',
        },
      ],
    }
  },
}
