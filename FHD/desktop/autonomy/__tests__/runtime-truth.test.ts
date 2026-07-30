import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {
  diskUsagePercent,
  diskFreeMegabytes,
  computeConfigFingerprint,
  resolveNeurobus,
  resolveLastBackup,
  hasPendingRollbackMarker,
  computeRuntimeTruth,
  deriveSignalsFromTruth,
  appendTruthLog,
} from '../runtime-truth.js'
import type { BackendRuntimeInfo, RuntimeTruthSnapshot } from '../types.js'

let tmpDir: string

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-autonomy-test-'))
})

afterEach(() => {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }) } catch { /* ignore */ }
})

describe('diskUsagePercent', () => {
  it('返回 0..100 之间的整数', () => {
    const pct = diskUsagePercent(tmpDir)
    expect(pct).toBeGreaterThanOrEqual(0)
    expect(pct).toBeLessThanOrEqual(100)
    expect(Number.isInteger(pct)).toBe(true)
  })

  it('路径不存在时返回 0', () => {
    const pct = diskUsagePercent(path.join(tmpDir, 'nonexistent'))
    expect(pct).toBe(0)
  })
})

describe('diskFreeMegabytes', () => {
  it('returns a non-negative integer for an accessible directory', () => {
    const freeMb = diskFreeMegabytes(tmpDir)
    if (freeMb === undefined) throw new Error('expected accessible temp directory')
    expect(freeMb).toBeGreaterThanOrEqual(0)
    expect(Number.isInteger(freeMb)).toBe(true)
  })

  it('returns undefined for a missing directory', () => {
    expect(diskFreeMegabytes(path.join(tmpDir, 'nonexistent'))).toBeUndefined()
  })
})

describe('computeConfigFingerprint', () => {
  it('configPath 为 null 时返回空字符串', () => {
    expect(computeConfigFingerprint(null)).toBe('')
  })

  it('文件不存在时返回空字符串', () => {
    expect(computeConfigFingerprint(path.join(tmpDir, 'no-such.json'))).toBe('')
  })

  it('相同内容返回相同指纹', () => {
    const f1 = path.join(tmpDir, 'c1.json')
    const f2 = path.join(tmpDir, 'c2.json')
    fs.writeFileSync(f1, '{"port":17500}', 'utf8')
    fs.writeFileSync(f2, '{"port":17500}', 'utf8')
    expect(computeConfigFingerprint(f1)).toBe(computeConfigFingerprint(f2))
  })

  it('不同内容返回不同指纹', () => {
    const f1 = path.join(tmpDir, 'c1.json')
    const f2 = path.join(tmpDir, 'c2.json')
    fs.writeFileSync(f1, '{"port":17500}', 'utf8')
    fs.writeFileSync(f2, '{"port":17501}', 'utf8')
    expect(computeConfigFingerprint(f1)).not.toBe(computeConfigFingerprint(f2))
  })

  it('指纹长度为 12', () => {
    const f = path.join(tmpDir, 'c.json')
    fs.writeFileSync(f, '{"port":17500}', 'utf8')
    const fp = computeConfigFingerprint(f)
    expect(fp).toHaveLength(12)
  })
})

describe('resolveNeurobus', () => {
  it('null/undefined 返回 undefined', () => {
    expect(resolveNeurobus(null)).toBeUndefined()
    expect(resolveNeurobus(undefined)).toBeUndefined()
  })

  it('非对象返回 undefined', () => {
    expect(resolveNeurobus('not-an-object')).toBeUndefined()
    expect(resolveNeurobus(42)).toBeUndefined()
  })

  it('对象返回解析结果', () => {
    const result = resolveNeurobus({ available: true, circuit_open: false, dlq_size: 5 })
    expect(result).toEqual({ available: true, circuit_open: false, dlq_size: 5 })
  })

  it('缺失字段用默认值', () => {
    const result = resolveNeurobus({})
    expect(result).toEqual({ available: false, circuit_open: false, dlq_size: 0 })
  })
})

describe('resolveLastBackup', () => {
  it('目录不存在返回 null', () => {
    expect(resolveLastBackup(path.join(tmpDir, 'no-backups'))).toBeNull()
  })

  it('空目录返回 null', () => {
    const backupsDir = path.join(tmpDir, 'backups')
    fs.mkdirSync(backupsDir)
    expect(resolveLastBackup(backupsDir)).toBeNull()
  })

  it('返回最新文件的 mtime', () => {
    const backupsDir = path.join(tmpDir, 'backups')
    fs.mkdirSync(backupsDir)
    const f1 = path.join(backupsDir, 'old.bak')
    const f2 = path.join(backupsDir, 'new.bak')
    const oldTime = new Date('2025-01-01').getTime()
    const newTime = Date.now()
    fs.writeFileSync(f1, 'old')
    fs.writeFileSync(f2, 'new')
    fs.utimesSync(f1, oldTime / 1000, oldTime / 1000)
    fs.utimesSync(f2, newTime / 1000, newTime / 1000)
    const result = resolveLastBackup(backupsDir)
    expect(result).not.toBeNull()
    expect(result).toBeGreaterThan(oldTime)
  })
})

describe('hasPendingRollbackMarker', () => {
  it('marker 不存在返回 false', () => {
    expect(hasPendingRollbackMarker(tmpDir)).toBe(false)
  })

  it('marker 存在返回 true', () => {
    fs.writeFileSync(path.join(tmpDir, 'rollback-marker.json'), '{}', 'utf8')
    expect(hasPendingRollbackMarker(tmpDir)).toBe(true)
  })
})

describe('computeRuntimeTruth', () => {
  it('返回完整 RuntimeTruthSnapshot', () => {
    const backend: BackendRuntimeInfo = { pid: 1234, running: true, startedAt: Date.now() - 1000 }
    const truth = computeRuntimeTruth({
      userDataDir: tmpDir,
      backend,
      portInUse: true,
      configPath: null,
      knownGoodFingerprint: null,
      appVersion: '10.0.0',
      buildSha: 'abc',
      restartCount: 0,
    })
    expect(truth.backend).toEqual(backend)
    expect(truth.port_in_use).toBe(true)
    expect(truth.app_version).toBe('10.0.0')
    expect(truth.build_sha).toBe('abc')
    expect(truth.restart_count).toBe(0)
    expect(truth.pending_rollback_marker).toBe(false)
    expect(truth.config_fingerprint_changed).toBe(false)
  })

  it('配置指纹变化时 config_fingerprint_changed=true', () => {
    const configPath = path.join(tmpDir, 'config.json')
    fs.writeFileSync(configPath, '{"port":17500}', 'utf8')
    const goodFingerprint = computeConfigFingerprint(configPath)
    // 修改配置
    fs.writeFileSync(configPath, '{"port":17501}', 'utf8')
    const truth = computeRuntimeTruth({
      userDataDir: tmpDir,
      backend: { pid: null, running: false, startedAt: null },
      portInUse: false,
      configPath,
      knownGoodFingerprint: goodFingerprint,
      appVersion: '10.0.0',
      buildSha: '',
      restartCount: 0,
    })
    expect(truth.config_fingerprint_changed).toBe(true)
  })

  it('配置指纹未变化时 config_fingerprint_changed=false', () => {
    const configPath = path.join(tmpDir, 'config.json')
    fs.writeFileSync(configPath, '{"port":17500}', 'utf8')
    const goodFingerprint = computeConfigFingerprint(configPath)
    const truth = computeRuntimeTruth({
      userDataDir: tmpDir,
      backend: { pid: null, running: false, startedAt: null },
      portInUse: false,
      configPath,
      knownGoodFingerprint: goodFingerprint,
      appVersion: '10.0.0',
      buildSha: '',
      restartCount: 0,
    })
    expect(truth.config_fingerprint_changed).toBe(false)
  })
})

describe('deriveSignalsFromTruth', () => {
  it('disk_usage >= 90 派生 disk_full 信号', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 95,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '10.0.0',
      build_sha: '',
      restart_count: 0,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'disk_full')).toBe(true)
  })

  it('disk_usage < 90 不派生 disk_full', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 80,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '10.0.0',
      build_sha: '',
      restart_count: 0,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'disk_full')).toBe(false)
  })

  it('config_fingerprint_changed 派生信号', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: true,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'config_fingerprint_changed')).toBe(true)
  })

  it('neurobus.circuit_open 派生 NEURO_BUS_CIRCUIT_OPEN', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      neurobus: { available: false, circuit_open: true, dlq_size: 5 },
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'NEURO_BUS_CIRCUIT_OPEN')).toBe(true)
  })

  it('neurobus.dlq_size > 1000 派生 NEURO_BUS_DLQ_FULL', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      neurobus: { available: true, circuit_open: false, dlq_size: 2000 },
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'NEURO_BUS_DLQ_FULL')).toBe(true)
  })

  it('neurobus.dlq_size <= 1000 不派生 DLQ_FULL', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      neurobus: { available: true, circuit_open: false, dlq_size: 500 },
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'NEURO_BUS_DLQ_FULL')).toBe(false)
  })

  it('reads circuit and DLQ facts from the real neurobus health shape', () => {
    expect(resolveNeurobus({
      status: 'healthy',
      running: true,
      reliability: { circuit_open: true },
      dlq_size: 1201,
    })).toEqual({ available: true, circuit_open: true, dlq_size: 1201 })
  })

  // Phase 1 新增：disk_low / db_corrupt / network_down 信号派生
  it('disk_free_mb < 500 派生 disk_low 信号', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      disk_free_mb: 200,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'disk_low' && s.severity === 'crit')).toBe(true)
  })

  it('disk_free_mb >= 500 不派生 disk_low', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      disk_free_mb: 1000,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'disk_low')).toBe(false)
  })

  it('disk_free_mb 未设置时不派生 disk_low', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'disk_low')).toBe(false)
  })

  it('db_integrity=fail 派生 db_corrupt 信号（fatal）', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      db_integrity: 'fail',
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'db_corrupt' && s.severity === 'fatal')).toBe(true)
  })

  it('db_integrity=ok 不派生 db_corrupt', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      db_integrity: 'ok',
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'db_corrupt')).toBe(false)
  })

  it('last_network_ok_ts 超过 5min 派生 network_down 信号', () => {
    const now = Date.now()
    const truth: RuntimeTruthSnapshot = {
      ts: now,
      backend: { pid: 1, running: true, startedAt: now },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      last_network_ok_ts: now - 10 * 60 * 1000, // 10 分钟前
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'network_down' && s.severity === 'warn')).toBe(true)
  })

  it('last_network_ok_ts 在 5min 内不派生 network_down', () => {
    const now = Date.now()
    const truth: RuntimeTruthSnapshot = {
      ts: now,
      backend: { pid: 1, running: true, startedAt: now },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      last_network_ok_ts: now - 60 * 1000, // 1 分钟前
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'network_down')).toBe(false)
  })

  it('last_network_ok_ts=null 不派生 network_down（从未成功不算断线）', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
      last_network_ok_ts: null,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals.some(s => s.kind === 'network_down')).toBe(false)
  })

  it('一切正常时不派生任何信号', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
    }
    const signals = deriveSignalsFromTruth(truth)
    expect(signals).toHaveLength(0)
  })
})

describe('appendTruthLog', () => {
  it('写入 truth.jsonl', () => {
    const truth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
    }
    appendTruthLog(tmpDir, truth)
    const logPath = path.join(tmpDir, 'autonomy', 'truth.jsonl')
    expect(fs.existsSync(logPath)).toBe(true)
    const content = fs.readFileSync(logPath, 'utf8').trim()
    const parsed = JSON.parse(content)
    expect(parsed.disk_usage_percent).toBe(50)
  })

  it('多次调用追加不覆盖', () => {
    const baseTruth: RuntimeTruthSnapshot = {
      ts: Date.now(),
      backend: { pid: 1, running: true, startedAt: Date.now() },
      port_in_use: true,
      disk_usage_percent: 50,
      config_fingerprint_changed: false,
      pending_rollback_marker: false,
      last_backup_ts: null,
      app_version: '',
      build_sha: '',
      restart_count: 0,
    }
    appendTruthLog(tmpDir, baseTruth)
    appendTruthLog(tmpDir, { ...baseTruth, disk_usage_percent: 60 })
    const logPath = path.join(tmpDir, 'autonomy', 'truth.jsonl')
    const lines = fs.readFileSync(logPath, 'utf8').trim().split('\n')
    expect(lines).toHaveLength(2)
  })
})
