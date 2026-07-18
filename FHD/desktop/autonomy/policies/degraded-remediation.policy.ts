/**
 * Policy：降级状态自动修复
 *
 * 触发：disk_full / config_fingerprint_changed / port_in_use /
 *       LLM_RUNTIME_UNAVAILABLE / NEURO_BUS_CIRCUIT_OPEN /
 *       NEURO_BUS_DLQ_FULL / NEURO_BUS_RATE_LIMIT
 *
 * 决策：按 kind 去重，每 kind 出一个动作：
 *   - disk_full → clear_cache (low)
 *   - config_fingerprint_changed → repair_config (medium)
 *   - port_in_use / LLM_RUNTIME_UNAVAILABLE / NEURO_BUS_* → escalate (high)
 */

import type { Policy, Signal, Action, Diagnosis } from '../types.js'
import { diagnoseRootCause } from '../rca-rules.js'

/** kind → 动作映射（每 kind 仅产出一个动作，避免重复） */
const KIND_TO_ACTION: Record<string, { type: Action['type']; risk: Action['risk']; max_attempts: number; idempotency_key: string }> = {
  disk_full: {
    type: 'clear_cache',
    risk: 'low',
    max_attempts: 2,
    idempotency_key: 'clear_cache:disk_full',
  },
  config_fingerprint_changed: {
    type: 'repair_config',
    risk: 'medium',
    max_attempts: 1,
    idempotency_key: 'repair_config:fingerprint_changed',
  },
  port_in_use: {
    type: 'escalate',
    risk: 'high',
    max_attempts: 1,
    idempotency_key: 'escalate:port_in_use',
  },
  LLM_RUNTIME_UNAVAILABLE: {
    type: 'escalate',
    risk: 'high',
    max_attempts: 1,
    idempotency_key: 'escalate:llm_unavailable',
  },
  NEURO_BUS_CIRCUIT_OPEN: {
    type: 'escalate',
    risk: 'high',
    max_attempts: 1,
    idempotency_key: 'escalate:neurobus_circuit',
  },
  NEURO_BUS_DLQ_FULL: {
    type: 'escalate',
    risk: 'high',
    max_attempts: 1,
    idempotency_key: 'escalate:neurobus_dlq',
  },
  NEURO_BUS_RATE_LIMIT: {
    type: 'escalate',
    risk: 'high',
    max_attempts: 1,
    idempotency_key: 'escalate:neurobus_rate_limit',
  },
}

export const degradedRemediationPolicy: Policy = {
  id: 'degraded-remediation',
  matches: Object.keys(KIND_TO_ACTION),
  gate: 'auto',
  plan(signals: Signal[]): { diagnosis: Diagnosis; actions: Action[] } {
    const diagnosis = diagnoseRootCause(signals)
    // 按 kind 去重：每 kind 只取最新一条信号
    const seenKinds = new Set<string>()
    const actions: Action[] = []
    // 按时间倒序处理，保留每 kind 最新信号
    const sorted = [...signals].sort((a, b) => b.ts - a.ts)
    for (const sig of sorted) {
      if (seenKinds.has(sig.kind)) continue
      seenKinds.add(sig.kind)
      const mapping = KIND_TO_ACTION[sig.kind]
      if (!mapping) continue
      actions.push({
        type: mapping.type,
        params: { reason: sig.detail, source_kind: sig.kind, ts: sig.ts },
        idempotency_key: mapping.idempotency_key,
        max_attempts: mapping.max_attempts,
        risk: mapping.risk,
      })
    }
    return { diagnosis, actions }
  },
}
