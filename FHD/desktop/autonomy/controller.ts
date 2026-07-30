/**
 * AutonomyController：自治系统核心调度器
 *
 * 职责：
 * - 接收信号（外部 ingest + 内部 truth 派生）
 * - 调用 Policy.plan() 决策
 * - ImpactPredictor 预检
 * - 调用 Adapter.executeAction()
 * - cooldown / max_attempts / escalate 守护
 * - 审计所有动作（含 skipped）
 *
 * 设计：与层级无关，只依赖 AutonomyAdapter 接口。
 */

import type {
  Action,
  AuditEntry,
  AutonomyAdapter,
  ControllerOptions,
  Diagnosis,
  Plan,
  Policy,
  RuntimeTruthSnapshot,
  Signal,
} from './types.js'
import { deriveSignalsFromTruth } from './runtime-truth.js'
import { predict } from './impact-predictor.js'
import {
  checkBeforeAction,
  isEnabled as crossTierGateEnabled,
  requiresRemoteState,
} from './cross-tier-gate.js'

/** 默认配置 */
const DEFAULTS = {
  enabled: true,
  pollIntervalMs: 5_000,
  signalRetentionMs: 30 * 60 * 1000,
  defaultCooldownMs: 5 * 60 * 1000,
} as const

/** 内部动作执行追踪 */
interface ActionTracker {
  idempotency_key: string
  attempts: number
  lastAttemptTs: number
  escalated: boolean
}

export class AutonomyController {
  private adapter: AutonomyAdapter
  private policies: Policy[]
  private opts: Required<ControllerOptions>
  private signals: Signal[] = []
  private trackers = new Map<string, ActionTracker>()
  private latestTruth: RuntimeTruthSnapshot | null = null
  private timer: NodeJS.Timeout | null = null
  private started = false
  /** 已处理过的 signal 去重（kind+ts），避免同一信号在多次 tick 中重复触发决策 */
  private processedSignalKeys = new Set<string>()

  constructor(adapter: AutonomyAdapter, policies: Policy[], opts: ControllerOptions = {}) {
    this.adapter = adapter
    this.policies = policies
    this.opts = {
      enabled: opts.enabled ?? DEFAULTS.enabled,
      pollIntervalMs: opts.pollIntervalMs ?? DEFAULTS.pollIntervalMs,
      signalRetentionMs: opts.signalRetentionMs ?? DEFAULTS.signalRetentionMs,
      defaultCooldownMs: opts.defaultCooldownMs ?? DEFAULTS.defaultCooldownMs,
    }
  }

  /** 启动周期 tick */
  start(): void {
    if (this.started || !this.opts.enabled) return
    this.started = true
    this.adapter.subscribeSignals((sig) => this.ingest(sig))
    this.timer = setInterval(() => { void this.tick() }, this.opts.pollIntervalMs)
  }

  /** 停止 tick */
  stop(): void {
    this.started = false
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  }

  /** 外部信号入口（如 main.ts 在 backend exit 时调用） */
  ingest(signal: Signal): void {
    this.signals.push(signal)
    this.pruneSignals()
  }

  /** 单次 tick：采集 truth → 派生信号 → 决策 → 执行
   *
   * 注：enabled 检查由 start() 负责（不启动定时器）；
   * 直接调用 tick() 始终执行，便于单元测试与"手动触发一次决策"的运维场景。
   */
  async tick(): Promise<void> {
    try {
      this.latestTruth = await this.adapter.collectTruth()
    } catch (e) {
      // truth 采集失败不阻塞决策（用旧 truth 或空）
      const detail = e instanceof Error ? e.message : String(e)
      this.adapter.audit({
        ts: new Date().toISOString(),
        source_signal: null,
        diagnosis: { root_cause: 'truth_collect_failed', confidence: 1, detail, evidence: [] },
        action: null,
        result: null,
      })
      return
    }
    // 从 truth 派生新信号
    const derived = deriveSignalsFromTruth(this.latestTruth)
    for (const sig of derived) {
      // 去重：相同 kind+ts 不重复 ingest
      if (!this.signals.some(s => s.kind === sig.kind && s.ts === sig.ts)) {
        this.ingest(sig)
      }
    }
    await this.process()
  }

  /** 决策 + 执行：按 policy 分组，每 policy 调用一次 plan() */
  private async process(): Promise<void> {
    if (this.signals.length === 0) return
    // 按 policy 分组信号
    for (const policy of this.policies) {
      const matched = this.signals.filter(s => policy.matches.includes(s.kind))
      if (matched.length === 0) continue
      // 只处理本 tick 新增的信号（去重）
      const newOnes = matched.filter(s => !this.processedSignalKeys.has(`${s.kind}:${s.ts}`))
      if (newOnes.length === 0) continue
      for (const s of newOnes) {
        this.processedSignalKeys.add(`${s.kind}:${s.ts}`)
      }
      const plan: Plan = policy.plan(matched)
      for (const action of plan.actions) {
        // 用最新信号作为 sourceSignal（审计需要）
        const sourceSignal = newOnes.sort((a, b) => b.ts - a.ts)[0]
        await this.tryExecute(action, plan.diagnosis, sourceSignal)
      }
    }
    this.pruneSignals()
    // 清理过期的 processedSignalKeys
    const cutoff = Date.now() - this.opts.signalRetentionMs
    for (const key of Array.from(this.processedSignalKeys)) {
      const tsStr = key.split(':').pop()
      const ts = Number(tsStr)
      if (Number.isFinite(ts) && ts < cutoff) {
        this.processedSignalKeys.delete(key)
      }
    }
  }

  /** 预检 + cooldown + max_attempts 守护 → 执行或 escalate */
  private async tryExecute(action: Action, diagnosis: Diagnosis, sourceSignal: Signal): Promise<void> {
    const tracker = this.getTracker(action.idempotency_key)
    // max_attempts 守护
    if (tracker.attempts >= action.max_attempts) {
      if (!tracker.escalated) {
        tracker.escalated = true
        await this.escalate(action, diagnosis, sourceSignal, 'max_attempts exhausted')
      }
      return
    }
    // cooldown 守护
    const now = Date.now()
    const cooldownMs = this.opts.defaultCooldownMs
    if (tracker.attempts > 0 && now - tracker.lastAttemptTs < cooldownMs) {
      // cooldown 内跳过（静默）
      return
    }
    // ImpactPredictor 预检
    const truth = this.latestTruth
    if (truth) {
      const prediction = predict(action, truth)
      if (!prediction.allow) {
        this.adapter.audit({
          ts: new Date().toISOString(),
          source_signal: sourceSignal,
          diagnosis,
          action: { type: 'skipped', reasons: prediction.reasons },
          result: null,
          truth_snapshot: truth,
        })
        return
      }
    }
    // CrossTierGate 只保护会影响其他端的版本/发布动作。本机可逆修复（如清缓存、
    // 恢复本机配置）不应因为离线而永久不可用；跨端动作仍查询失败即 fail-closed。
    if (crossTierGateEnabled() && requiresRemoteState(action.type)) {
      let remoteState: Record<string, unknown> | null = null
      try {
        remoteState = (await this.adapter.getRemoteState?.()) ?? null
      } catch (e) {
        // 查询失败：记 audit；remoteState=null → Gate fail-closed 阻断
        const detail = e instanceof Error ? e.message : String(e)
        this.adapter.audit({
          ts: new Date().toISOString(),
          source_signal: sourceSignal,
          diagnosis,
          action: { type: 'skipped', reasons: [`cross_tier_query_failed: ${detail}`] },
          result: null,
          truth_snapshot: truth ?? undefined,
        })
        remoteState = null
      }
      const gateResult = checkBeforeAction('desktop', action.type, remoteState)
      if (!gateResult.allow) {
        this.adapter.audit({
          ts: new Date().toISOString(),
          source_signal: sourceSignal,
          diagnosis,
          action: { type: 'skipped', reasons: gateResult.reasons },
          result: null,
          truth_snapshot: truth ?? undefined,
        })
        return
      }
    }
    // 执行
    tracker.attempts += 1
    tracker.lastAttemptTs = now
    let result
    try {
      result = await this.adapter.executeAction(action)
    } catch (e) {
      result = {
        action,
        ok: false,
        detail: `execute_threw: ${e instanceof Error ? e.message : String(e)}`,
        ts: Date.now(),
      }
    }
    // 审计
    const entry: AuditEntry = {
      ts: new Date().toISOString(),
      source_signal: sourceSignal,
      diagnosis,
      action,
      result,
      truth_snapshot: truth ?? undefined,
    }
    this.adapter.audit(entry)
    // 失败且耗尽 attempts → escalate
    if (!result.ok && tracker.attempts >= action.max_attempts && !tracker.escalated) {
      tracker.escalated = true
      await this.escalate(action, diagnosis, sourceSignal, result.detail)
    }
  }

  /** 升级到人工处理：写 audit + 触发 escalate 动作 */
  private async escalate(action: Action, diagnosis: Diagnosis, sourceSignal: Signal, reason: string): Promise<void> {
    const escalateAction: Action = {
      type: 'escalate',
      params: { original_action: action.type, reason, diagnosis_root_cause: diagnosis.root_cause },
      idempotency_key: `escalate:${action.idempotency_key}`,
      max_attempts: 1,
      risk: 'high',
    }
    try {
      const result = await this.adapter.executeAction(escalateAction)
      this.adapter.audit({
        ts: new Date().toISOString(),
        source_signal: sourceSignal,
        diagnosis,
        action: escalateAction,
        result,
        truth_snapshot: this.latestTruth ?? undefined,
      })
    } catch (e) {
      // escalate 失败仅记录，不再上抛
      this.adapter.audit({
        ts: new Date().toISOString(),
        source_signal: sourceSignal,
        diagnosis,
        action: escalateAction,
        result: {
          action: escalateAction,
          ok: false,
          detail: `escalate_threw: ${e instanceof Error ? e.message : String(e)}`,
          ts: Date.now(),
        },
      })
    }
  }

  /** 获取或创建动作追踪器 */
  private getTracker(idempotencyKey: string): ActionTracker {
    let tracker = this.trackers.get(idempotencyKey)
    if (!tracker) {
      tracker = { idempotency_key: idempotencyKey, attempts: 0, lastAttemptTs: 0, escalated: false }
      this.trackers.set(idempotencyKey, tracker)
    }
    return tracker
  }

  /** 清理过期信号 */
  private pruneSignals(): void {
    const cutoff = Date.now() - this.opts.signalRetentionMs
    this.signals = this.signals.filter(s => s.ts >= cutoff)
  }

  /** 测试用：暴露当前信号列表（只读视图） */
  _signalsForTest(): readonly Signal[] {
    return this.signals
  }

  /** 测试用：暴露当前 truth */
  _truthForTest(): RuntimeTruthSnapshot | null {
    return this.latestTruth
  }
}
