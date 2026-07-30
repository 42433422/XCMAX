import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// The adapter only needs Electron's userData path in production.  Keep this
// unit suite runnable in plain Node without downloading an Electron binary.
const electronMocks = vi.hoisted(() => ({
  app: { getPath: vi.fn(() => '') },
}))
vi.mock('electron', () => electronMocks)

import { DesktopAutonomyAdapter } from '../desktop-adapter.js'
import type { DesktopAdapterContext } from '../desktop-adapter.js'
import type { Action, BackendRuntimeInfo } from '../types.js'

let tmpDir: string

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-desktop-adapter-test-'))
})

afterEach(() => {
  vi.unstubAllGlobals()
  try { fs.rmSync(tmpDir, { recursive: true, force: true }) } catch { /* ignore */ }
})

/** 构造测试用 ctx，restartBackend/triggerRollback 默认 vi.fn() */
function makeCtx(overrides: Partial<DesktopAdapterContext> = {}): DesktopAdapterContext {
  const backend: BackendRuntimeInfo = { pid: null, running: false, startedAt: null }
  return {
    backendProcessRef: () => ({ ...backend }),
    restartCountRef: () => 0,
    port: 17500,
    appVersion: '10.0.0',
    buildSha: 'test-sha',
    configPath: null,
    restartBackend: vi.fn(async () => { /* mock */ }),
    triggerRollback: vi.fn(async () => { /* mock */ }),
    knownGoodConfigContent: null,
    ...overrides,
  }
}

/** 构造 Action 对象 */
function makeAction(type: Action['type'], params: Record<string, unknown> = {}): Action {
  return {
    type,
    params,
    idempotency_key: `test:${type}`,
    max_attempts: 1,
    risk: 'low',
  }
}

describe('DesktopAutonomyAdapter.executeAction', () => {
  describe('restart_backend', () => {
    it('成功路径：调用 ctx.restartBackend 返回 ok=true', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('restart_backend'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('backend restart triggered')
      expect(ctx.restartBackend).toHaveBeenCalledTimes(1)
    })

    it('未注入 restartBackend 时返回 ok=false', async () => {
      const ctx = makeCtx({ restartBackend: undefined })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('restart_backend'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('restartBackend callback not injected')
    })

    it('restartBackend 抛错时返回 ok=false 且 detail 包含错误信息', async () => {
      const ctx = makeCtx({
        restartBackend: vi.fn(async () => { throw new Error('spawn failed') }),
      })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('restart_backend'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('execute_threw')
      expect(result.detail).toContain('spawn failed')
    })

    it('restartBackend 明确未确认启动时不把动作记为成功', async () => {
      const ctx = makeCtx({ restartBackend: vi.fn(async () => false) })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('restart_backend'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('not confirmed')
    })
  })

  describe('rollback_version', () => {
    it('成功路径：已安排回滚后返回 ok=true', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('rollback_version'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('rollback triggered')
      expect(ctx.triggerRollback).toHaveBeenCalledTimes(1)
    })

    it('回滚未安排时拒绝把动作记为成功', async () => {
      const ctx = makeCtx({ triggerRollback: vi.fn(async () => false) })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('rollback_version'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('rollback was not scheduled')
      expect(ctx.triggerRollback).toHaveBeenCalledTimes(1)
    })

    it('未注入 triggerRollback 时拒绝回滚', async () => {
      const ctx = makeCtx({ triggerRollback: undefined })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('rollback_version'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('triggerRollback callback not injected')
    })

    it('triggerRollback 抛错时返回 ok=false', async () => {
      const ctx = makeCtx({
        triggerRollback: vi.fn(async () => { throw new Error('rollback network error') }),
      })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('rollback_version'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('execute_threw')
      expect(result.detail).toContain('rollback network error')
    })
  })

  describe('clear_cache', () => {
    it('cache 和 neurobus_cache 都不存在时 cleared=0', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('clear_cache'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('cleared 0 cache dirs')
    })

    it('cache 和 neurobus_cache 都存在时 cleared=2', async () => {
      fs.mkdirSync(path.join(tmpDir, 'cache'))
      fs.writeFileSync(path.join(tmpDir, 'cache', 'a.txt'), 'a')
      fs.mkdirSync(path.join(tmpDir, 'neurobus_cache'))
      fs.writeFileSync(path.join(tmpDir, 'neurobus_cache', 'b.txt'), 'b')
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('clear_cache'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('cleared 2 cache dirs')
      expect(fs.existsSync(path.join(tmpDir, 'cache'))).toBe(false)
      expect(fs.existsSync(path.join(tmpDir, 'neurobus_cache'))).toBe(false)
    })

    it('仅 cache 存在时 cleared=1', async () => {
      fs.mkdirSync(path.join(tmpDir, 'cache'))
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('clear_cache'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('cleared 1 cache dirs')
    })

    it('backups 目录不被清理', async () => {
      const backupsDir = path.join(tmpDir, 'backups')
      fs.mkdirSync(backupsDir)
      fs.writeFileSync(path.join(backupsDir, 'important.bak'), 'critical')
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      await adapter.executeAction(makeAction('clear_cache'))
      expect(fs.existsSync(path.join(backupsDir, 'important.bak'))).toBe(true)
    })
  })

  describe('repair_config', () => {
    it('configPath=null 时拒绝', async () => {
      const ctx = makeCtx({ configPath: null, knownGoodConfigContent: '{"port":17500}' })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('repair_config'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('no configPath configured')
    })

    it('knownGoodConfigContent=null 时拒绝', async () => {
      const configPath = path.join(tmpDir, 'config.json')
      fs.writeFileSync(configPath, '{"port":17500}', 'utf8')
      const ctx = makeCtx({ configPath, knownGoodConfigContent: null })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('repair_config'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('no known-good config content to restore')
    })

    it('成功路径：生成备份文件并恢复配置内容', async () => {
      const configPath = path.join(tmpDir, 'config.json')
      const originalContent = '{"port":17501,"bad":"drifted"}'
      const knownGoodContent = '{"port":17500}'
      fs.writeFileSync(configPath, originalContent, 'utf8')
      const ctx = makeCtx({ configPath, knownGoodConfigContent: knownGoodContent })
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('repair_config'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('config restored')
      expect(result.detail).toContain('autonomy-bak-')
      // 当前配置文件内容应被恢复为 knownGoodContent
      const currentContent = fs.readFileSync(configPath, 'utf8')
      expect(currentContent).toBe(knownGoodContent)
      // 备份文件应包含原始内容
      // detail 格式：`config restored (backup: <path>)`，regex 需排除末尾 `)`
      const backupMatch = result.detail.match(/backup: (.+?)\)$/)
      expect(backupMatch).not.toBeNull()
      const backupPath = backupMatch![1]
      expect(fs.existsSync(backupPath)).toBe(true)
      const backupContent = fs.readFileSync(backupPath, 'utf8')
      expect(backupContent).toBe(originalContent)
    })

    it('可从当前桌面 database profile 快照恢复被篡改的配置', async () => {
      const configPath = path.join(tmpDir, 'database.json')
      const knownGoodContent = '{"mode":"local","remote":{"enabled":false}}\n'
      fs.writeFileSync(configPath, knownGoodContent, 'utf8')
      const adapter = DesktopAutonomyAdapter.forTest(makeCtx({ configPath }), tmpDir)
      expect(adapter.captureKnownGoodConfigSnapshot()).not.toBeNull()
      fs.writeFileSync(configPath, '{"mode":"remote","remote":{"enabled":true}}\n', 'utf8')

      const result = await adapter.executeAction(makeAction('repair_config'))

      expect(result.ok).toBe(true)
      expect(fs.readFileSync(configPath, 'utf8')).toBe(knownGoodContent)
    })
  })

  describe('escalate / noop', () => {
    it('escalate 返回 ok=true', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('escalate'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('escalate acknowledged')
    })

    it('noop 返回 ok=true', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('noop'))
      expect(result.ok).toBe(true)
      expect(result.detail).toContain('noop acknowledged')
    })
  })

  describe('未实现的 action', () => {
    it('restart_service 返回 ok=false not-implemented', async () => {
      const ctx = makeCtx()
      const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
      const result = await adapter.executeAction(makeAction('restart_service'))
      expect(result.ok).toBe(false)
      expect(result.detail).toContain('not-implemented:restart_service')
    })
  })
})

describe('DesktopAutonomyAdapter.collectTruth', () => {
  it('collects the separate NeuroBus health facts used by the remediation policy', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/api/desktop/status')) {
        return { ok: true, json: async () => ({ readyForUi: true }) }
      }
      return {
        ok: true,
        json: async () => ({
          status: 'healthy',
          running: true,
          reliability: { circuit_open: true },
          dlq_size: 1002,
        }),
      }
    })
    vi.stubGlobal('fetch', fetchMock)
    const adapter = DesktopAutonomyAdapter.forTest(makeCtx({ port: 0 }), tmpDir)

    const truth = await adapter.collectTruth()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(truth.neurobus).toEqual({ available: true, circuit_open: true, dlq_size: 1002 })
    expect(truth.disk_free_mb).toBeGreaterThanOrEqual(0)
  })
})

describe('DesktopAutonomyAdapter.audit', () => {
  it('执行 action 后 audit.jsonl 包含完整 entry', async () => {
    const ctx = makeCtx()
    const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
    await adapter.executeAction(makeAction('clear_cache'))
    adapter.audit({
      ts: new Date().toISOString(),
      source_signal: null,
      diagnosis: null,
      action: makeAction('clear_cache'),
      result: { action: makeAction('clear_cache'), ok: true, detail: 'test', ts: Date.now() },
    })
    const auditPath = path.join(tmpDir, 'autonomy', 'audit.jsonl')
    expect(fs.existsSync(auditPath)).toBe(true)
    const lines = fs.readFileSync(auditPath, 'utf8').trim().split('\n')
    expect(lines.length).toBe(1)
    const entry = JSON.parse(lines[0])
    expect(entry.action.type).toBe('clear_cache')
    expect(entry.result.ok).toBe(true)
  })

  it('audit 写入失败不抛错', () => {
    const ctx = makeCtx()
    const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
    // 删除 autonomy 目录模拟写入失败
    fs.rmSync(path.join(tmpDir, 'autonomy'), { recursive: true, force: true })
    expect(() => {
      adapter.audit({
        ts: new Date().toISOString(),
        source_signal: null,
        diagnosis: null,
        action: null,
        result: null,
      })
    }).not.toThrow()
  })
})

describe('DesktopAutonomyAdapter.computeCurrentFingerprint', () => {
  it('configPath=null 返回空字符串', () => {
    const ctx = makeCtx({ configPath: null })
    const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
    expect(adapter.computeCurrentFingerprint()).toBe('')
  })

  it('configPath 存在返回 12 位指纹', () => {
    const configPath = path.join(tmpDir, 'config.json')
    fs.writeFileSync(configPath, '{"port":17500}', 'utf8')
    const ctx = makeCtx({ configPath })
    const adapter = DesktopAutonomyAdapter.forTest(ctx, tmpDir)
    const fp = adapter.computeCurrentFingerprint()
    expect(fp).toHaveLength(12)
  })
})

describe('DesktopAutonomyAdapter.captureKnownGoodConfigSnapshot', () => {
  it('keeps configuration fingerprint available for drift detection', () => {
    const configPath = path.join(tmpDir, 'config.json')
    fs.writeFileSync(configPath, '{"port":17500}', 'utf8')
    const adapter = DesktopAutonomyAdapter.forTest(makeCtx({ configPath }), tmpDir)
    expect(adapter.captureKnownGoodConfigSnapshot()).toHaveLength(12)
    expect(adapter.computeCurrentFingerprint()).toHaveLength(12)
  })
})
