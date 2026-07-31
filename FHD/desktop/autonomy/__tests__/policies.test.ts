import { describe, it, expect } from 'vitest'
import { backendCrashPolicy } from '../policies/backend-crash.policy.js'
import { degradedRemediationPolicy } from '../policies/degraded-remediation.policy.js'
import { updateRollbackPolicy } from '../policies/update-rollback.policy.js'
import type { Signal } from '../types.js'

function makeSignal(kind: string, ts: number, overrides: Partial<Signal> = {}): Signal {
  return {
    source: 'test',
    kind,
    severity: 'warn',
    detail: `${kind} at ${ts}`,
    ts,
    ...overrides,
  }
}

describe('backendCrashPolicy', () => {
  it('matches 包含 backend_exit', () => {
    expect(backendCrashPolicy.matches).toContain('backend_exit')
  })

  it('gate 为 auto', () => {
    expect(backendCrashPolicy.gate).toBe('auto')
  })

  it('空信号返回空 actions', () => {
    const plan = backendCrashPolicy.plan([])
    expect(plan.actions).toHaveLength(0)
    expect(plan.diagnosis.root_cause).toBe('unknown')
  })

  it('5min 窗口内 <3 次崩溃不触发回滚', () => {
    const now = 1_000_000
    const signals = [
      makeSignal('backend_exit', now - 100_000),
      makeSignal('backend_exit', now - 50_000),
    ]
    const plan = backendCrashPolicy.plan(signals)
    expect(plan.actions).toHaveLength(0)
  })

  it('5min 窗口内 ≥3 次崩溃触发回滚', () => {
    const now = 1_000_000
    const signals = [
      makeSignal('backend_exit', now - 200_000), // 200s 前，在 5min 窗口内
      makeSignal('backend_exit', now - 100_000),
      makeSignal('backend_exit', now - 50_000),
    ]
    const plan = backendCrashPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
    expect(plan.actions[0].type).toBe('rollback_version')
    expect(plan.actions[0].risk).toBe('high')
    expect(plan.actions[0].max_attempts).toBe(1)
    expect(plan.actions[0].idempotency_key).toBe('rollback:backend-crash')
    expect(plan.actions[0].params.reason).toContain('3 次')
  })

  it('5min 窗口边界：刚好 3 次（含最早一条在窗口边界）触发', () => {
    const now = 1_000_000
    const windowMs = 5 * 60 * 1000
    // 最早一条刚好在 now - windowMs（边界）
    const signals = [
      makeSignal('backend_exit', now - windowMs),
      makeSignal('backend_exit', now - 100_000),
      makeSignal('backend_exit', now - 50_000),
    ]
    const plan = backendCrashPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
  })

  it('5min 窗口外（>5min）的崩溃不计入', () => {
    // 注：policy 用 latest signal ts 作"now"（纯函数，禁用 Date.now()）
    // 故需相对 latest signal ts 构造窗口外信号
    const latestTs = 1_000_000
    const windowMs = 5 * 60 * 1000
    const signals = [
      makeSignal('backend_exit', latestTs - 50_000 - windowMs - 1), // 相对 latest 窗口外
      makeSignal('backend_exit', latestTs - 100_000),
      makeSignal('backend_exit', latestTs - 50_000), // latest，policy 用此作 now
    ]
    const plan = backendCrashPolicy.plan(signals)
    expect(plan.actions).toHaveLength(0)
  })

  it('诊断 root_cause 为 backend_crash', () => {
    const signals = [makeSignal('backend_exit', Date.now())]
    const plan = backendCrashPolicy.plan(signals)
    expect(plan.diagnosis.root_cause).toBe('backend_crash')
  })
})

describe('degradedRemediationPolicy', () => {
  it('matches 包含 10 个 kind（Phase 1 新增 disk_low / db_corrupt / network_down）', () => {
    expect(degradedRemediationPolicy.matches).toContain('disk_full')
    expect(degradedRemediationPolicy.matches).toContain('config_fingerprint_changed')
    expect(degradedRemediationPolicy.matches).toContain('port_in_use')
    expect(degradedRemediationPolicy.matches).toContain('LLM_RUNTIME_UNAVAILABLE')
    expect(degradedRemediationPolicy.matches).toContain('NEURO_BUS_CIRCUIT_OPEN')
    expect(degradedRemediationPolicy.matches).toContain('NEURO_BUS_DLQ_FULL')
    expect(degradedRemediationPolicy.matches).toContain('NEURO_BUS_RATE_LIMIT')
    expect(degradedRemediationPolicy.matches).toContain('disk_low')
    expect(degradedRemediationPolicy.matches).toContain('db_corrupt')
    expect(degradedRemediationPolicy.matches).toContain('network_down')
    expect(degradedRemediationPolicy.matches).toHaveLength(10)
  })

  it('disk_full → clear_cache (low)', () => {
    const signals = [makeSignal('disk_full', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
    expect(plan.actions[0].type).toBe('clear_cache')
    expect(plan.actions[0].risk).toBe('low')
    expect(plan.actions[0].max_attempts).toBe(2)
  })

  it('config_fingerprint_changed → repair_config (medium)', () => {
    const signals = [makeSignal('config_fingerprint_changed', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
    expect(plan.actions[0].type).toBe('repair_config')
    expect(plan.actions[0].risk).toBe('medium')
  })

  it('port_in_use → escalate (high)', () => {
    const signals = [makeSignal('port_in_use', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
    expect(plan.actions[0].type).toBe('escalate')
    expect(plan.actions[0].risk).toBe('high')
  })

  it('LLM_RUNTIME_UNAVAILABLE → escalate', () => {
    const signals = [makeSignal('LLM_RUNTIME_UNAVAILABLE', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions[0].type).toBe('escalate')
  })

  it('NEURO_BUS_CIRCUIT_OPEN → restart_backend once', () => {
    const signals = [makeSignal('NEURO_BUS_CIRCUIT_OPEN', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions[0].type).toBe('restart_backend')
    expect(plan.actions[0].risk).toBe('medium')
    expect(plan.actions[0].max_attempts).toBe(1)
  })

  it('NEURO_BUS_DLQ_FULL → escalate', () => {
    const signals = [makeSignal('NEURO_BUS_DLQ_FULL', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions[0].type).toBe('escalate')
  })

  it('NEURO_BUS_RATE_LIMIT → escalate', () => {
    const signals = [makeSignal('NEURO_BUS_RATE_LIMIT', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions[0].type).toBe('escalate')
  })

  it('disk_low → clear_cache (low)', () => {
    const signals = [makeSignal('disk_low', Date.now())]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions[0].type).toBe('clear_cache')
    expect(plan.actions[0].risk).toBe('low')
  })

  it('按 kind 去重：同 kind 多条信号只产出一个动作', () => {
    const now = Date.now()
    const signals = [
      makeSignal('disk_full', now - 1000),
      makeSignal('disk_full', now - 500),
      makeSignal('disk_full', now),
    ]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
  })

  it('多 kind 混合：每 kind 一个动作', () => {
    const now = Date.now()
    const signals = [
      makeSignal('disk_full', now),
      makeSignal('config_fingerprint_changed', now),
      makeSignal('port_in_use', now),
    ]
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.actions).toHaveLength(3)
    const types = plan.actions.map(a => a.type).sort()
    expect(types).toEqual(['clear_cache', 'escalate', 'repair_config'])
  })

  it('诊断 evidence 包含最近 5 条信号', () => {
    const now = Date.now()
    const signals = Array.from({ length: 7 }, (_, i) => makeSignal('disk_full', now - i * 1000))
    const plan = degradedRemediationPolicy.plan(signals)
    expect(plan.diagnosis.evidence.length).toBeLessThanOrEqual(5)
  })
})

describe('updateRollbackPolicy', () => {
  it('matches 包含 ota_install_failed', () => {
    expect(updateRollbackPolicy.matches).toContain('ota_install_failed')
  })

  it('空信号返回空 actions', () => {
    const plan = updateRollbackPolicy.plan([])
    expect(plan.actions).toHaveLength(0)
  })

  it('ota_install_failed → rollback_version', () => {
    const signals = [makeSignal('ota_install_failed', Date.now(), {
      detail: 'signature mismatch',
      payload: { reason: 'Ed25519 校验失败' },
    })]
    const plan = updateRollbackPolicy.plan(signals)
    expect(plan.actions).toHaveLength(1)
    expect(plan.actions[0].type).toBe('rollback_version')
    expect(plan.actions[0].risk).toBe('high')
    expect(plan.actions[0].max_attempts).toBe(1)
  })

  it('从 payload.reason 提取回滚原因', () => {
    const signals = [makeSignal('ota_install_failed', Date.now(), {
      payload: { reason: '哈希不匹配' },
    })]
    const plan = updateRollbackPolicy.plan(signals)
    expect(plan.actions[0].params.reason).toBe('哈希不匹配')
  })

  it('无 payload.reason 时用 detail', () => {
    const signals = [makeSignal('ota_install_failed', Date.now(), {
      detail: 'fallback detail',
    })]
    const plan = updateRollbackPolicy.plan(signals)
    expect(plan.actions[0].params.reason).toBe('fallback detail')
  })

  it('idempotency_key 固定', () => {
    const signals = [makeSignal('ota_install_failed', Date.now())]
    const plan = updateRollbackPolicy.plan(signals)
    expect(plan.actions[0].idempotency_key).toBe('rollback:ota-install-failed')
  })
})
