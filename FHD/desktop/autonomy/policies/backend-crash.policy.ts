/**
 * Policy：backend 崩溃自动回滚
 *
 * 触发：backend_exit 信号
 * 决策：窗口内崩溃次数 ≥ 自适应 crash_threshold → rollback_version
 *
 * 硬编码 CRASH_THRESHOLD=3 已降级为 adaptive-thresholds（floor=2, ceiling=5）。
 * 不发 restart_backend：main.ts 已有自动重启逻辑。
 */

import type { Policy, Signal, Action, Diagnosis } from '../types.js'
import { diagnoseRootCause } from '../rca-rules.js'
import { getThreshold } from '../adaptive-thresholds.js'

export const backendCrashPolicy: Policy = {
  id: 'backend-crash',
  matches: ['backend_exit'],
  gate: 'auto',
  plan(signals: Signal[]): { diagnosis: Diagnosis; actions: Action[] } {
    const diagnosis = diagnoseRootCause(signals)
    const exits = signals
      .filter(s => s.kind === 'backend_exit')
      .sort((a, b) => a.ts - b.ts)
    if (exits.length === 0) return { diagnosis, actions: [] }

    const crashThreshold = Math.round(getThreshold('crash_threshold').value)
    const windowMs = Math.round(getThreshold('crash_window_ms').value)

    // 用最新信号的 ts 作为"现在"（纯函数，禁止 Date.now()）
    const now = exits[exits.length - 1].ts
    const recent = exits.filter(s => s.ts >= now - windowMs)
    if (recent.length < crashThreshold) {
      return { diagnosis, actions: [] }
    }
    const reason =
      `backend ${Math.round(windowMs / 60000)}min 内崩溃 ${recent.length} 次，` +
      `超过自适应阈值 ${crashThreshold}（floor/ceiling 受控）`
    return {
      diagnosis,
      actions: [
        {
          type: 'rollback_version',
          params: {
            reason,
            crash_count: recent.length,
            window_ms: windowMs,
            crash_threshold: crashThreshold,
            threshold_source: 'adaptive',
          },
          idempotency_key: 'rollback:backend-crash',
          max_attempts: 1,
          risk: 'high',
        },
      ],
    }
  },
}
