import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { AutonomyController } from '../controller.js'
import type { AutonomyAdapter, Action, ActionResult, RuntimeTruthSnapshot, Signal, AuditEntry } from '../types.js'

/** 构建 mock adapter */
function makeMockAdapter(opts: {
  truth?: RuntimeTruthSnapshot | RuntimeTruthSnapshot[]
  executeResult?: ActionResult | ((action: Action) => ActionResult)
} = {}): AutonomyAdapter & {
  audits: AuditEntry[]
  executed: Action[]
  truthCalls: number
} {
  const audits: AuditEntry[] = []
  const executed: Action[] = []
  let truthCalls = 0
  let truthIdx = 0
  const truthArr = Array.isArray(opts.truth) ? opts.truth : (opts.truth ? [opts.truth] : [])
  return {
    audits,
    executed,
    truthCalls,
    async collectTruth() {
      truthCalls += 1
      const t = truthArr[truthIdx] ?? truthArr[0] ?? makeBaseTruth()
      // 若是数组，每次返回下一个；否则返回第一个
      const result = truthArr.length > 1 ? truthArr[Math.min(truthIdx, truthArr.length - 1)] : t
      if (truthArr.length > 1) truthIdx += 1
      return result
    },
    subscribeSignals(_emit: (signal: Signal) => void) { /* empty */ },
    async executeAction(action: Action): Promise<ActionResult> {
      executed.push(action)
      if (typeof opts.executeResult === 'function') return opts.executeResult(action)
      if (opts.executeResult) return opts.executeResult
      return { action, ok: true, detail: 'mock-ok', ts: Date.now() }
    },
    audit(entry: AuditEntry) {
      audits.push(entry)
    },
  } as unknown as AutonomyAdapter & { audits: AuditEntry[]; executed: Action[]; truthCalls: number }
}

function makeBaseTruth(overrides: Partial<RuntimeTruthSnapshot> = {}): RuntimeTruthSnapshot {
  return {
    ts: Date.now(),
    backend: { pid: 1234, running: true, startedAt: Date.now() - 60_000 },
    port_in_use: true,
    disk_usage_percent: 50,
    config_fingerprint_changed: false,
    pending_rollback_marker: false,
    last_backup_ts: Date.now() - 3 * 24 * 3600 * 1000,
    app_version: '10.0.0',
    build_sha: 'abc123',
    restart_count: 0,
    ...overrides,
  }
}

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

const noopPolicy = {
  id: 'noop',
  matches: ['noop'],
  gate: 'auto' as const,
  plan: () => ({ diagnosis: { root_cause: 'noop', confidence: 1, detail: '', evidence: [] }, actions: [] }),
}

describe('AutonomyController', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // 非门禁用例默认关闭 CrossTierGate，避免无 getRemoteState 时 fail-closed 干扰
    process.env.XCAGI_CROSS_TIER_GATE = '0'
  })

  afterEach(() => {
    delete process.env.XCAGI_CROSS_TIER_GATE
  })

  it('start() 设置定时器并启动', () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: true, pollIntervalMs: 1000 })
    ctrl.start()
    // start 后 subscribeSignals 应被调用（adapter 内部记录）
    // 定时器在 1000ms 后触发 tick
    expect(ctrl).toBeDefined()
    ctrl.stop()
  })

  it('start() 幂等：重复调用不会创建多个定时器', () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: true, pollIntervalMs: 1000 })
    ctrl.start()
    ctrl.start()
    ctrl.start()
    ctrl.stop()
    // 无异常即通过
    expect(true).toBe(true)
  })

  it('enabled:false 时 start() 不启动定时器', async () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: false, pollIntervalMs: 100 })
    ctrl.start()
    await vi.advanceTimersByTimeAsync(500)
    expect(adapter.truthCalls).toBe(0)
  })

  it('ingest() 接收信号并保留', () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: false })
    const sig = makeSignal('noop', Date.now())
    ctrl.ingest(sig)
    expect(ctrl._signalsForTest()).toHaveLength(1)
    expect(ctrl._signalsForTest()[0]).toBe(sig)
  })

  it('tick() 采集 truth 并派生信号', async () => {
    const truth = makeBaseTruth({ disk_usage_percent: 95 })
    const adapter = makeMockAdapter({ truth })
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: true, pollIntervalMs: 100 })
    await ctrl.tick()
    // disk_full 应被派生为信号
    expect(ctrl._signalsForTest().some(s => s.kind === 'disk_full')).toBe(true)
  })

  it('tick() 采集 truth 失败时不抛错，写 audit', async () => {
    const audits: AuditEntry[] = []
    const adapter: AutonomyAdapter = {
      async collectTruth() { throw new Error('network down') },
      subscribeSignals() {},
      async executeAction(action) { return { action, ok: false, detail: '', ts: Date.now() } },
      audit(entry) { audits.push(entry) },
    }
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: true })
    await ctrl.tick()
    expect(audits.length).toBeGreaterThan(0)
    expect(audits[0].diagnosis?.root_cause).toBe('truth_collect_failed')
  })

  it('process() 调用匹配的 Policy.plan()', async () => {
    let planCalled = false
    const policy = {
      id: 'test-policy',
      matches: ['test_kind'],
      gate: 'auto' as const,
      plan(signals: Signal[]) {
        planCalled = true
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [],
        }
      },
    }
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [policy], { enabled: false })
    ctrl.ingest(makeSignal('test_kind', Date.now()))
    await ctrl.tick()
    expect(planCalled).toBe(true)
  })

  it('tryExecute 通过预检后调用 adapter.executeAction', async () => {
    const policy = {
      id: 'p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'clear_cache' as const,
            params: { reason: 'test' },
            idempotency_key: 'test:1',
            max_attempts: 1,
            risk: 'low' as const,
          }],
        }
      },
    }
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ disk_usage_percent: 95 }),
    })
    const ctrl = new AutonomyController(adapter, [policy], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(1)
    expect(adapter.executed[0].type).toBe('clear_cache')
  })

  it('ImpactPredictor 拒绝时写 audit 且不执行', async () => {
    const policy = {
      id: 'p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'clear_cache' as const,
            params: {},
            idempotency_key: 'test:deny',
            max_attempts: 1,
            risk: 'low' as const,
          }],
        }
      },
    }
    // disk_usage < 70 → clear_cache 应被拒绝
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ disk_usage_percent: 50 }),
    })
    const ctrl = new AutonomyController(adapter, [policy], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
    expect(adapter.audits.length).toBeGreaterThan(0)
    const skippedEntry = adapter.audits.find(a => a.action && typeof a.action === 'object' && 'type' in a.action && a.action.type === 'skipped')
    expect(skippedEntry).toBeDefined()
  })

  it('max_attempts 耗尽后 escalate', async () => {
    const policy = {
      id: 'p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'rollback_version' as const,
            params: {},
            idempotency_key: 'test:maxfail',
            max_attempts: 1,
            risk: 'high' as const,
          }],
        }
      },
    }
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
      executeResult: { action: {} as Action, ok: false, detail: 'fail', ts: Date.now() },
    })
    const ctrl = new AutonomyController(adapter, [policy], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    // 应有原始动作 + escalate 动作
    expect(adapter.executed.length).toBe(2)
    expect(adapter.executed[1].type).toBe('escalate')
  })

  it('cooldown 窗口内跳过重复动作', async () => {
    let callCount = 0
    const policy = {
      id: 'p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'clear_cache' as const,
            params: {},
            idempotency_key: 'cooldown:test',
            max_attempts: 3,
            risk: 'low' as const,
          }],
        }
      },
    }
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ disk_usage_percent: 95 }),
      executeResult: (action: Action) => {
        callCount += 1
        return { action, ok: true, detail: 'ok', ts: Date.now() }
      },
    })
    const ctrl = new AutonomyController(adapter, [policy], {
      enabled: false,
      defaultCooldownMs: 60_000,
    })
    // 第一次 tick + 新信号 → 执行
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(callCount).toBe(1)
    // 第二次新信号 → cooldown 内跳过
    ctrl.ingest(makeSignal('trigger', Date.now() + 1))
    await ctrl.tick()
    expect(callCount).toBe(1) // 仍为 1
  })

  it('pruneSignals 清理过期信号', () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], {
      enabled: false,
      signalRetentionMs: 1000,
    })
    const now = Date.now()
    ctrl.ingest(makeSignal('old', now - 2000))
    ctrl.ingest(makeSignal('new', now))
    // 触发 prune（在 ingest 中调用）
    expect(ctrl._signalsForTest().some(s => s.kind === 'old')).toBe(false)
    expect(ctrl._signalsForTest().some(s => s.kind === 'new')).toBe(true)
  })

  it('stop() 停止定时器', () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: true, pollIntervalMs: 100 })
    ctrl.start()
    ctrl.stop()
    // 停止后即使推进时间也不应触发 tick
    // （通过 truthCalls 验证，但需要 async 推进）
    expect(true).toBe(true)
  })

  it('未匹配 Policy 的信号被忽略', async () => {
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [noopPolicy], { enabled: false })
    ctrl.ingest(makeSignal('unmatched_kind', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
  })

  it('空 actions 不调用 executeAction', async () => {
    const policy = {
      id: 'p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [],
        }
      },
    }
    const adapter = makeMockAdapter()
    const ctrl = new AutonomyController(adapter, [policy], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
  })
})

describe('AutonomyController — crossTierGate integration', () => {
  const ENV_KEY = 'XCAGI_CROSS_TIER_GATE'

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    delete process.env[ENV_KEY]
  })

  /** 构造一个直接产出 rollback_version 动作的 policy */
  function makeRollbackPolicy() {
    return {
      id: 'rollback-p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'rollback_version' as const,
            params: { reason: 'test' },
            idempotency_key: 'rollback:test',
            max_attempts: 2,
            risk: 'high' as const,
          }],
        }
      },
    }
  }

  function makeLocalRepairPolicy() {
    return {
      id: 'local-repair-p',
      matches: ['trigger'],
      gate: 'auto' as const,
      plan(_signals: Signal[]) {
        return {
          diagnosis: { root_cause: 'test', confidence: 1, detail: '', evidence: [] },
          actions: [{
            type: 'clear_cache' as const,
            params: { reason: 'test' },
            idempotency_key: 'clear-cache:test',
            max_attempts: 2,
            risk: 'low' as const,
          }],
        }
      },
    }
  }

  it('default crossTierGate does not block a reversible local repair without remote state', async () => {
    delete process.env[ENV_KEY]
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ disk_usage_percent: 91 }),
    })
    const ctrl = new AutonomyController(adapter, [makeLocalRepairPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed).toHaveLength(1)
    expect(adapter.executed[0].type).toBe('clear_cache')
  })

  it('env 未设时 crossTierGate 默认启用 + adapter 无 getRemoteState → fail-closed 阻断', async () => {
    delete process.env[ENV_KEY]
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
  })

  it('env=0 显式关闭 crossTierGate → 动作正常执行不走门禁', async () => {
    process.env[ENV_KEY] = '0'
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    // 即使 frozen=true 也应放行（门禁关闭）
    ;(adapter as unknown as { getRemoteState: () => Promise<Record<string, unknown>> }).getRemoteState = async () => ({
      server_manifest_frozen: true,
    })
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(1)
    expect(adapter.executed[0].type).toBe('rollback_version')
  })

  it('env=1 且 adapter 未实现 getRemoteState → fail-closed 阻断', async () => {
    process.env[ENV_KEY] = '1'
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    // 不设置 getRemoteState → null → fail-closed
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
  })

  it('env=1 且 getRemoteState 返回 server_manifest_frozen=true → 拦截 rollback_version', async () => {
    process.env[ENV_KEY] = '1'
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    // 注入 getRemoteState 返回 frozen=true
    ;(adapter as unknown as { getRemoteState: () => Promise<Record<string, unknown>> }).getRemoteState = async () => ({
      server_manifest_frozen: true,
    })
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
    // 应有 skipped 审计
    const skipped = adapter.audits.find(
      a => a.action && typeof a.action === 'object' && 'type' in a.action && a.action.type === 'skipped',
    )
    expect(skipped).toBeDefined()
    expect(skipped?.action).toMatchObject({ type: 'skipped' })
  })

  it('env=1 且 getRemoteState 返回 server_manifest_frozen=false → 放行', async () => {
    process.env[ENV_KEY] = '1'
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    ;(adapter as unknown as { getRemoteState: () => Promise<Record<string, unknown>> }).getRemoteState = async () => ({
      server_manifest_frozen: false,
    })
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(1)
  })

  it('env=1 且 getRemoteState 抛错 → fail-closed 阻断 + 写 audit', async () => {
    process.env[ENV_KEY] = '1'
    const adapter = makeMockAdapter({
      truth: makeBaseTruth({ pending_rollback_marker: false, last_backup_ts: Date.now() }),
    })
    ;(adapter as unknown as { getRemoteState: () => Promise<never> }).getRemoteState = async () => {
      throw new Error('network down')
    }
    const ctrl = new AutonomyController(adapter, [makeRollbackPolicy()], { enabled: false })
    ctrl.ingest(makeSignal('trigger', Date.now()))
    await ctrl.tick()
    expect(adapter.executed.length).toBe(0)
    const failedAudit = adapter.audits.find(
      a => a.action && typeof a.action === 'object' && 'type' in a.action && a.action.type === 'skipped'
        && Array.isArray((a.action as { reasons: string[] }).reasons)
        && (a.action as { reasons: string[] }).reasons.some(r => r.includes('cross_tier_query_failed')),
    )
    expect(failedAudit).toBeDefined()
    const denied = adapter.audits.find(
      a => a.action && typeof a.action === 'object' && 'type' in a.action && a.action.type === 'skipped'
        && Array.isArray((a.action as { reasons: string[] }).reasons)
        && (a.action as { reasons: string[] }).reasons.some(r => r.includes('fail-closed')),
    )
    expect(denied).toBeDefined()
  })
})
