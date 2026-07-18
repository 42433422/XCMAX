/**
 * Policy：backend 崩溃自动回滚
 *
 * 触发：backend_exit 信号
 * 决策：5 分钟窗口内 ≥3 次崩溃 → rollback_version（high 风险，max_attempts=1）
 *
 * 不发 restart_backend：main.ts 已有 restartCount≤3 自动重启逻辑，
 * 控制器仅在崩溃频率超阈值时回滚，避免重复动作。
 */

import type { Policy, Signal, Action, Diagnosis } from '../types.js'
import { diagnoseRootCause } from '../rca-rules.js'

/** 5 分钟窗口毫秒数 */
const ROLLBACK_WINDOW_MS = 5 * 60 * 1000

/** 崩溃阈值：5min 内 ≥3 次触发回滚 */
const CRASH_THRESHOLD = 3

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
    // 用最新信号的 ts 作为"现在"（纯函数，禁止 Date.now()）
    const now = exits[exits.length - 1].ts
    const recent = exits.filter(s => s.ts >= now - ROLLBACK_WINDOW_MS)
    if (recent.length < CRASH_THRESHOLD) {
      return { diagnosis, actions: [] }
    }
    const reason = `backend 5min 内崩溃 ${recent.length} 次，超过阈值 ${CRASH_THRESHOLD}`
    return {
      diagnosis,
      actions: [
        {
          type: 'rollback_version',
          params: { reason, crash_count: recent.length, window_ms: ROLLBACK_WINDOW_MS },
          idempotency_key: 'rollback:backend-crash',
          max_attempts: 1,
          risk: 'high',
        },
      ],
    }
  },
}
