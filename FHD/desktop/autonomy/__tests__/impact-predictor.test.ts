import { describe, it, expect } from 'vitest'
import { predict } from '../impact-predictor.js'
import type { Action, RuntimeTruthSnapshot } from '../types.js'

function makeTruth(overrides: Partial<RuntimeTruthSnapshot> = {}): RuntimeTruthSnapshot {
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

function makeAction(overrides: Partial<Action> = {}): Action {
  return {
    type: 'clear_cache',
    params: {},
    idempotency_key: 'test:1',
    max_attempts: 1,
    risk: 'low',
    ...overrides,
  }
}

describe('impact-predictor predict()', () => {
  describe('restart_backend', () => {
    it('backend 启动不足 10s 时拒绝', () => {
      const truth = makeTruth({
        backend: { pid: 1, running: true, startedAt: Date.now() - 5_000 },
      })
      const action = makeAction({ type: 'restart_backend' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('启动不足')
    })

    it('端口未占用时拒绝', () => {
      const truth = makeTruth({
        port_in_use: false,
        backend: { pid: null, running: false, startedAt: null },
      })
      const action = makeAction({ type: 'restart_backend' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons.some(r => r.includes('端口未占用'))).toBe(true)
    })

    it('restart_count >= 3 时拒绝并建议 escalate', () => {
      const truth = makeTruth({ restart_count: 3 })
      const action = makeAction({ type: 'restart_backend' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.suggestions).toBeDefined()
      expect(result.suggestions?.some(s => s.includes('escalate'))).toBe(true)
    })

    it('正常运行 + 端口占用 + restart_count<3 时允许', () => {
      const truth = makeTruth({ restart_count: 1 })
      const action = makeAction({ type: 'restart_backend' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
      expect(result.reasons).toHaveLength(0)
    })
  })

  describe('rollback_version', () => {
    it('存在 pending rollback marker 时拒绝（嵌套回滚）', () => {
      const truth = makeTruth({ pending_rollback_marker: true })
      const action = makeAction({ type: 'rollback_version' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('嵌套回滚')
    })

    it('无备份时拒绝', () => {
      const truth = makeTruth({ last_backup_ts: null, pending_rollback_marker: false })
      const action = makeAction({ type: 'rollback_version' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons.some(r => r.includes('无已知备份'))).toBe(true)
    })

    it('备份超过 7 天时拒绝并建议先备份', () => {
      const truth = makeTruth({
        last_backup_ts: Date.now() - 8 * 24 * 3600 * 1000,
        pending_rollback_marker: false,
      })
      const action = makeAction({ type: 'rollback_version' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.suggestions?.some(s => s.includes('手动备份'))).toBe(true)
    })

    it('无 marker + 新鲜备份时允许', () => {
      const truth = makeTruth({
        pending_rollback_marker: false,
        last_backup_ts: Date.now() - 1 * 24 * 3600 * 1000,
      })
      const action = makeAction({ type: 'rollback_version' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })
  })

  describe('clear_cache', () => {
    it('磁盘占用 < 70% 时拒绝', () => {
      const truth = makeTruth({ disk_usage_percent: 50 })
      const action = makeAction({ type: 'clear_cache' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('无需清理')
    })

    it('磁盘占用 >= 70% 时允许', () => {
      const truth = makeTruth({ disk_usage_percent: 75 })
      const action = makeAction({ type: 'clear_cache' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('边界：磁盘占用 = 70% 时拒绝', () => {
      const truth = makeTruth({ disk_usage_percent: 70 })
      const action = makeAction({ type: 'clear_cache' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
    })

    it('边界：磁盘占用 = 69% 时拒绝', () => {
      const truth = makeTruth({ disk_usage_percent: 69 })
      const action = makeAction({ type: 'clear_cache' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
    })
  })

  describe('repair_config', () => {
    it('配置未漂移时拒绝', () => {
      const truth = makeTruth({ config_fingerprint_changed: false })
      const action = makeAction({ type: 'repair_config' })
      const result = predict(action, truth)
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('未漂移')
    })

    it('配置漂移时允许', () => {
      const truth = makeTruth({ config_fingerprint_changed: true })
      const action = makeAction({ type: 'repair_config' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })
  })

  describe('服务器端动作', () => {
    it('restart_service 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'restart_service' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('rollback_to_last_tarball 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'rollback_to_last_tarball' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('freeze_manifest 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'freeze_manifest' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('clear_logs 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'clear_logs' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('escalate 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'escalate' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })

    it('noop 桌面端不预检（允许）', () => {
      const truth = makeTruth()
      const action = makeAction({ type: 'noop' })
      const result = predict(action, truth)
      expect(result.allow).toBe(true)
    })
  })
})
