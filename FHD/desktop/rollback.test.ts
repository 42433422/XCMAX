import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import { createHash } from 'node:crypto'
import os from 'node:os'
import path from 'node:path'
const electronMocks = vi.hoisted(() => {
  const nodeOs = require('node:os')
  const nodePath = require('node:path')
  const nodeFs = require('node:fs')
  const tmpDir = nodeOs.tmpdir()
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  const userDataDir = nodePath.join(tmpDir, `xcagi-rollback-test-${stamp}`)
  nodeFs.mkdirSync(userDataDir, { recursive: true })
  const state = {
    exePath: nodePath.join(tmpDir, `xcagi-rollback-app-${stamp}`, 'XCAGI.exe')
  }
  return {
    app: {
      isPackaged: false as boolean,
      getPath: (name: string) => {
        if (name === 'userData') return userDataDir
        if (name === 'exe') return state.exePath
        return nodePath.join(tmpDir, `xcagi-rollback-mock-${name}`)
      },
      getVersion: () => '10.0.0'
    },
    __userDataDir: userDataDir,
    __state: state
  }
})
vi.mock('electron', () => electronMocks)
const windowsRollbackMocks = vi.hoisted(() => ({
  launchWindowsFullRollback: vi.fn(async (..._args: unknown[]) => 12345)
}))
const macosRollbackMocks = vi.hoisted(() => ({
  launchMacOSFullRollback: vi.fn(async () => 12345)
}))
const windowsOnly = process.platform === 'win32' ? it : it.skip
vi.mock('./rollback-windows.js', async importOriginal => {
  const actual = await importOriginal<typeof import('./rollback-windows.js')>()
  return {
    ...actual,
    launchWindowsFullRollback: windowsRollbackMocks.launchWindowsFullRollback
  }
})
vi.mock('./rollback-macos.js', async importOriginal => {
  const actual = await importOriginal<typeof import('./rollback-macos.js')>()
  return { ...actual, launchMacOSFullRollback: macosRollbackMocks.launchMacOSFullRollback }
})
function cleanRollbackState() {
  const userData = electronMocks.__userDataDir
  const rollbackDir = path.join(userData, 'rollback')
  try { fs.rmSync(rollbackDir, { recursive: true, force: true }) } catch {}
  try { fs.unlinkSync(path.join(userData, 'rollback-marker.json')) } catch {}
  try { fs.unlinkSync(path.join(userData, 'rollback-applied.json')) } catch {}
}
beforeEach(() => {
  cleanRollbackState()
  vi.resetModules()
})
describe('rollback — prepareRollback', () => {
  let tmpResources: string
  let tmpAppBundle: string
  let savedResourcesPath: string | undefined
  beforeEach(() => {
    electronMocks.app.isPackaged = true
    tmpAppBundle = path.join(os.tmpdir(), `xcagi-rollback-${Date.now()}-${Math.random().toString(36).slice(2)}.app`)
    tmpResources = process.platform === 'darwin' ? path.join(tmpAppBundle, 'Contents', 'Resources') : path.join(tmpAppBundle, 'Resources')
    fs.mkdirSync(tmpResources, { recursive: true })
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(backendDir, exeName), 'fake-binary-content')
    fs.mkdirSync(path.join(backendDir, '_internal'), { recursive: true })
    fs.writeFileSync(path.join(backendDir, '_internal', 'config.json'), '{"k":"v"}')
    const appPath = process.platform === 'darwin'
      ? path.join(tmpAppBundle, 'Contents', 'MacOS', 'XCAGI')
      : path.join(tmpResources, 'XCAGI.exe')
    fs.mkdirSync(path.dirname(appPath), { recursive: true })
    fs.writeFileSync(appPath, 'fake-app')
    electronMocks.__state.exePath = appPath
    savedResourcesPath = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
  })
  afterEach(() => {
    electronMocks.app.isPackaged = false
    if (savedResourcesPath === undefined) {
      delete (process as { resourcesPath?: string }).resourcesPath
    } else {
      (process as { resourcesPath?: string }).resourcesPath = savedResourcesPath
    }
  })
  it('skips prepareRollback in dev mode (not packaged)', async () => {
    electronMocks.app.isPackaged = false
    const { prepareRollback } = await import('./rollback.js')
    await expect(prepareRollback('10.0.1')).resolves.toBeUndefined()
  })
  windowsOnly('snapshots supported Mod and SQLite state and passes its inventory to the shared helper', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const userData = electronMocks.__userDataDir
      const write = (relative: string, value: string) => {
        const target = path.join(userData, relative)
        fs.mkdirSync(path.dirname(target), { recursive: true })
        fs.writeFileSync(target, value)
      }
      write('mods/northwind/manifest.json', '{"id":"northwind","version":"2.3.0"}')
      fs.mkdirSync(path.join(userData, 'mods', 'northwind', 'empty-preserved'), { recursive: true })
      write('mods/customer-reporting/backend/report.py', 'authorized customer Mod')
      write('mods/northwind/logs/private.log', 'excluded log')
      write('products__northwind.db', 'per-Mod DB')
      write('data/mod_dbs/customer-reporting.db', 'private Mod DB')
      write('data/xcagi.db', 'main DB')
      windowsRollbackMocks.launchWindowsFullRollback.mockClear()
      const { prepareRollback, checkPendingRollback, triggerRollback } = await import('./rollback.js')
      await prepareRollback('10.3.0')
      const marker = checkPendingRollback()
      const preparedMarkerBytes = fs.readFileSync(path.join(userData, 'rollback-marker.json'))
      const preparedSnapshotRoot = marker?.ownedBackupRoot
      expect(preparedSnapshotRoot).toBeTruthy()
      const preparedSnapshotHash = createHash('sha256').update(fs.readFileSync(path.join(preparedSnapshotRoot!, 'mods', 'northwind', 'manifest.json'))).digest('hex')
      await expect(prepareRollback('10.3.1')).rejects.toThrow(/未完成的更新回滚记录/)
      expect(fs.readFileSync(path.join(userData, 'rollback-marker.json'))).toEqual(preparedMarkerBytes)
      expect(createHash('sha256').update(fs.readFileSync(path.join(preparedSnapshotRoot!, 'mods', 'northwind', 'manifest.json'))).digest('hex')).toBe(preparedSnapshotHash)
      expect(marker?.expectedOwnedFiles).toMatchObject({
        'mods\\northwind\\manifest.json': expect.any(String),
        'mods\\customer-reporting\\backend\\report.py': expect.any(String),
        'products__northwind.db': expect.any(String),
        'data\\mod_dbs\\customer-reporting.db': expect.any(String),
      })
      expect(marker?.expectedOwnedFiles).not.toHaveProperty('data\\xcagi.db')
      expect(marker?.expectedOwnedDirectories).toContain('mods\\northwind\\empty-preserved')
      expect(Object.keys(marker?.expectedOwnedFiles || {}).some(name => name.includes('private.log'))).toBe(false)
      await triggerRollback('test owned state handoff')
      const options = windowsRollbackMocks.launchWindowsFullRollback.mock.calls[0]?.[0] as { ownedUserDataRoot?: string; ownedBackupRoot?: string; expectedOwnedFiles?: Record<string, string>; expectedOwnedDirectories?: string[] }
      expect(options.ownedUserDataRoot).toBe(userData)
      expect(options.ownedBackupRoot).toBe(marker?.ownedBackupRoot)
      expect(options.expectedOwnedFiles).toEqual(marker?.expectedOwnedFiles)
      expect(options.expectedOwnedDirectories).toEqual(marker?.expectedOwnedDirectories)
      const rollbackRoot = path.join(userData, 'rollback')
      const unrelatedFailedSnapshot = path.join(rollbackRoot, 'windows-owned-state-failed-preserved')
      const unrelatedUnknownFolder = path.join(rollbackRoot, 'unknown-retained-folder')
      fs.mkdirSync(unrelatedFailedSnapshot)
      fs.writeFileSync(path.join(unrelatedFailedSnapshot, 'keep.txt'), 'failed snapshot')
      fs.mkdirSync(unrelatedUnknownFolder)
      fs.writeFileSync(path.join(unrelatedUnknownFolder, 'keep.txt'), 'unknown artifact')
      const { commitRollback } = await import('./rollback.js')
      commitRollback()
      expect(fs.existsSync(preparedSnapshotRoot!)).toBe(false)
      expect(fs.readFileSync(path.join(unrelatedFailedSnapshot, 'keep.txt'), 'utf8')).toBe('failed snapshot')
      expect(fs.readFileSync(path.join(unrelatedUnknownFolder, 'keep.txt'), 'utf8')).toBe('unknown artifact')
    } finally {
      cleanup()
    }
  })
  it.each([false, true])('backs up the app when obsolete backup cleanup fails=%s', async cleanupFails => {
    const { prepareRollback, checkPendingRollback } = await import('./rollback.js')
    await prepareRollback('10.0.1')
    const marker = checkPendingRollback()
    expect(marker).not.toBeNull()
    expect(marker!.fromVersion).toBe('10.0.0')
    expect(marker!.toVersion).toBe('10.0.1')
    if (process.platform === 'win32') {
      expect(marker!.mode).toBe('windows-full')
      expect(marker!.appBackupRelPath).toBe('windows-app-current')
    } else if (process.platform === 'darwin') {
      expect(marker!.mode).toBe('macos-full')
      expect(marker!.appBackupRelPath).toBe('macos-app-current.app')
    } else {
      expect(marker!.backupRelPath).toMatch(/^backend-10\.0\.0$/)
    }
    const userData = electronMocks.__userDataDir
    const backupRoot = path.join(userData, 'rollback', marker!.appBackupRelPath || marker!.backupRelPath!)
    expect(fs.existsSync(backupRoot)).toBe(true)
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    const backendBackupRoot =
      process.platform === 'win32'
        ? path.join(backupRoot, 'backend')
        : process.platform === 'darwin'
          ? path.join(backupRoot, 'Contents', 'Resources', 'backend')
          : backupRoot
    expect(fs.existsSync(path.join(backendBackupRoot, exeName))).toBe(true)
    expect(fs.existsSync(path.join(backendBackupRoot, '_internal', 'config.json'))).toBe(true)
    const { commitRollback } = await import('./rollback.js')
    commitRollback()
    const remove = fs.rmSync.bind(fs)
    vi.spyOn(fs, 'rmSync').mockImplementation((target, options) => {
      if (cleanupFails && String(target).includes('.failed-') && fs.existsSync(target)) {
        throw Object.assign(new Error('obsolete backup ENOTEMPTY'), { code: 'ENOTEMPTY' })
      }
      return remove(target, options)
    })
    await expect(prepareRollback('10.0.2')).resolves.toBeUndefined()
    expect(checkPendingRollback()?.toVersion).toBe('10.0.2')
    expect(fs.readFileSync(path.join(backendBackupRoot, exeName), 'utf8')).toBe('fake-binary-content')
  })
  it('throws when backend executable missing', async () => {
    const backendDir = path.join(tmpResources, 'backend')
    fs.rmSync(backendDir, { recursive: true, force: true })
    const { prepareRollback } = await import('./rollback.js')
    await expect(prepareRollback('10.0.1')).rejects.toThrow(/找不到当前 backend/)
  })
})
describe('rollback — commitRollback', () => {
  it('deletes marker file', async () => {
    const { prepareRollback, commitRollback, checkPendingRollback } = await import('./rollback.js')
    const cleanup = setupPackagedBackend()
    try {
      await prepareRollback('10.0.3')
      expect(checkPendingRollback()).not.toBeNull()
      commitRollback()
      expect(checkPendingRollback()).toBeNull()
    } finally {
      cleanup()
    }
  })
})
describe('rollback — triggerRollback', () => {
  it('returns silently when no marker (not update first-run)', async () => {
    const { triggerRollback } = await import('./rollback.js')
    await expect(triggerRollback('test reason')).resolves.toEqual({
      mode: 'none',
      scheduled: false
    })
  })
})
describe('rollback — consumeRollbackApplied', () => {
  it('returns the applied record only once', async () => {
    const appliedPath = path.join(electronMocks.__userDataDir, 'rollback-applied.json')
    fs.writeFileSync(
      appliedPath,
      JSON.stringify({
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: 'test',
        fromVersion: 'new',
        toVersion: 'old'
      })
    )
    const { consumeRollbackApplied } = await import('./rollback.js')
    expect(consumeRollbackApplied()?.reason).toBe('test')
    expect(consumeRollbackApplied()).toBeNull()
  })
})

const windowsIt = process.platform === 'win32' ? it : it.skip
describe('rollback — Windows full app restore scheduling', () => {
  windowsIt('hashes authorized owned files with bounded reads while preparing the snapshot', async () => {
    const cleanup = setupPackagedBackend()
    const modFile = path.join(electronMocks.__userDataDir, 'mods', 'stream-test', 'payload.bin')
    fs.mkdirSync(path.dirname(modFile), { recursive: true })
    fs.writeFileSync(modFile, Buffer.alloc(5 * 1024 * 1024, 0x5a))
    type ReadSyncOptionsForTest = { offset?: number; length?: number; position?: number | null }
    type ReadSyncForTest = (...args: [number, ArrayBufferView, number, number, number | null] | [number, ArrayBufferView, ReadSyncOptionsForTest]) => number
    const originalReadSync = fs.readSync.bind(fs) as unknown as ReadSyncForTest
    const readSync = vi.spyOn(fs, 'readSync')
    const requested: number[] = []
    readSync.mockImplementation(((fd: number, buffer: ArrayBufferView, offsetOrOptions: number | ReadSyncOptionsForTest, length?: number, position?: number | null) => {
      if (typeof offsetOrOptions === 'number') {
        const requestedLength = length ?? buffer.byteLength
        requested.push(requestedLength)
        return originalReadSync(fd, buffer, offsetOrOptions, requestedLength, position ?? null)
      }
      requested.push(offsetOrOptions.length ?? buffer.byteLength)
      return originalReadSync(fd, buffer, offsetOrOptions)
    }) as typeof fs.readSync)
    try {
      const { prepareRollback } = await import('./rollback.js')
      await prepareRollback('10.0.6')
      expect(requested.length).toBeGreaterThan(0)
      expect(Math.max(...requested)).toBeLessThanOrEqual(1024 * 1024)
    } finally {
      readSync.mockRestore()
      cleanup()
    }
  })
  windowsIt('passes an absent database baseline through triggerRollback to the real helper', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, triggerRollback } = await import('./rollback.js')
      await prepareRollback('10.0.6')
      const markerPath = path.join(electronMocks.__userDataDir, 'rollback-marker.json')
      const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'))
      const database = path.join(electronMocks.__userDataDir, 'data', 'xcagi.db')
      Object.assign(marker, { databasePath: database, databaseBackupPath: '', databaseOriginallyAbsent: true })
      fs.writeFileSync(markerPath, JSON.stringify(marker)); fs.mkdirSync(path.dirname(database), { recursive: true })
      for (const suffix of ['', '-wal', '-shm', '-journal']) fs.writeFileSync(database + suffix, 'failed candidate')
      windowsRollbackMocks.launchWindowsFullRollback.mockImplementationOnce(async (...args: unknown[]) => {
        const options = args[0] as import('./rollback-windows.js').WindowsRollbackLaunchOptions
        expect(options.databasePath).toBe(database); expect(options.databaseOriginallyAbsent).toBe(true)
        const actual = await vi.importActual<typeof import('./rollback-windows.js')>('./rollback-windows.js')
        const { execFileSync } = await import('node:child_process')
        const script = actual.buildWindowsRollbackScript({ ...options, currentPid: 2_000_000_000, restartApp: false })
        const scriptPath = path.join(electronMocks.__userDataDir, 'rollback', 'owned-state-integration.ps1')
        fs.writeFileSync(scriptPath, script, 'utf8')
        const sha256 = createHash('sha256').update(script).digest('hex')
        const loader = actual.buildWindowsRollbackFileLoader(scriptPath, sha256)
        const encoded = Buffer.from(loader, 'utf16le').toString('base64')
        expect(encoded.length).toBeLessThan(32767)
        execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { timeout: 15000 })
        return 12345
      })
      await triggerRollback('startup failed')
      for (const suffix of ['', '-wal', '-shm', '-journal']) expect(fs.existsSync(database + suffix)).toBe(false)
      expect(fs.existsSync(markerPath)).toBe(false)
      expect(fs.existsSync(path.join(electronMocks.__userDataDir, 'rollback-applied.json'))).toBe(true)
    } finally { cleanup() }
  })
  windowsIt('launches the external helper and leaves marker consumption to it', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, triggerRollback, checkPendingRollback } = await import('./rollback.js')
      await prepareRollback('10.0.6')
      const result = await triggerRollback('window failed')
      expect(result).toEqual({ mode: 'windows-full', scheduled: true })
      expect(windowsRollbackMocks.launchWindowsFullRollback).toHaveBeenCalledOnce()
      expect(checkPendingRollback()).not.toBeNull()
    } finally {
      cleanup()
    }
  })
})

function setupPackagedBackend(): () => void {
  electronMocks.app.isPackaged = true
  const tmpAppBundle = path.join(
    os.tmpdir(),
    `xcagi-rollback-ext-${Date.now()}-${Math.random().toString(36).slice(2)}.app`,
  )
  const tmpResources = process.platform === 'darwin'
    ? path.join(tmpAppBundle, 'Contents', 'Resources')
    : tmpAppBundle
  const backendDir = path.join(tmpResources, 'backend')
  fs.mkdirSync(backendDir, { recursive: true })
  const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
  fs.writeFileSync(path.join(backendDir, exeName), 'fake-backend')
  const appPath = process.platform === 'darwin'
    ? path.join(tmpAppBundle, 'Contents', 'MacOS', 'XCAGI')
    : path.join(tmpResources, 'XCAGI.exe')
  fs.mkdirSync(path.dirname(appPath), { recursive: true })
  fs.writeFileSync(appPath, 'fake-app')
  electronMocks.__state.exePath = appPath
  const saved = (process as { resourcesPath?: string }).resourcesPath
  ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
  return () => {
    if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
    else (process as { resourcesPath?: string }).resourcesPath = saved
    electronMocks.app.isPackaged = false
    fs.rmSync(tmpAppBundle, { recursive: true, force: true })
  }
}

describe('rollback — attachDatabaseBackupToRollback', () => {
  it('throws when no marker exists', async () => {
    const { attachDatabaseBackupToRollback } = await import('./rollback.js')
    expect(() => attachDatabaseBackupToRollback('/tmp/any.db.bak')).toThrow(/缺少 rollback marker/)
  })

  it('attaches a valid backup inside userData to the marker', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, attachDatabaseBackupToRollback, checkPendingRollback } = await import(
        './rollback.js'
      )
      await prepareRollback('10.1.0')
      const backupPath = path.join(electronMocks.__userDataDir, 'backups', 'pre-migrate.db')
      fs.mkdirSync(path.dirname(backupPath), { recursive: true })
      fs.writeFileSync(backupPath, 'db-snapshot')

      attachDatabaseBackupToRollback(backupPath)
      const marker = checkPendingRollback()
      expect(marker?.databaseBackupPath).toBe(backupPath)
      expect(marker?.databasePath).toBe(path.join(electronMocks.__userDataDir, 'data', 'xcagi.db'))
    } finally {
      cleanup()
    }
  })

  it('rejects outside and missing backups', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, attachDatabaseBackupToRollback } = await import('./rollback.js')
      await prepareRollback('10.1.2')
      expect(() => attachDatabaseBackupToRollback('/tmp/outside.db')).toThrow(/不在 XCAGI 数据目录内/)
      const missing = path.join(electronMocks.__userDataDir, 'backups', 'missing.db')
      expect(() => attachDatabaseBackupToRollback(missing)).toThrow(/数据库备份不存在/)
    } finally {
      cleanup()
    }
  })
})

describe('rollback — cancelPreparedRollback', () => {
  it('removes a prepared marker and is idempotent without one', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, cancelPreparedRollback, checkPendingRollback } = await import(
        './rollback.js'
      )
      await prepareRollback('10.2.0')
      expect(checkPendingRollback()).not.toBeNull()
      cancelPreparedRollback()
      expect(checkPendingRollback()).toBeNull()
      expect(() => cancelPreparedRollback()).not.toThrow()
    } finally {
      cleanup()
    }
  })

  it('keeps a Windows recovery-required marker durable when updater cleanup runs', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const markerPath = path.join(electronMocks.__userDataDir, 'rollback-marker.json')
      fs.writeFileSync(markerPath, JSON.stringify({ mode: 'windows-full', fromVersion: 'old', toVersion: 'candidate', preparedAt: '2026-10-12T00:00:00.000Z', backendPath: 'backend.exe', recoveryRequired: false }))
      const { markPreparedRollbackRecoveryRequired, clearPreparedRollbackRecoveryRequired, cancelPreparedRollback, commitRollback, checkPendingRollback } = await import('./rollback.js')
      markPreparedRollbackRecoveryRequired()
      cancelPreparedRollback()
      expect(checkPendingRollback()?.recoveryRequired).toBe(true)
      expect(fs.existsSync(markerPath)).toBe(true)
      clearPreparedRollbackRecoveryRequired()
      expect(checkPendingRollback()?.recoveryRequired).toBe(false)
      cancelPreparedRollback()
      expect(fs.existsSync(markerPath)).toBe(true)
      commitRollback()
      expect(fs.existsSync(markerPath)).toBe(false)
    } finally {
      cleanup()
    }
  })

  it('preserves the complete prepared marker and refuses cancellation when durable replacement fails', async () => {
    const cleanup = setupPackagedBackend()
    const markerPath = path.join(electronMocks.__userDataDir, 'rollback-marker.json')
    const before = JSON.stringify({ mode: 'windows-full', fromVersion: '1.0.0+' + 'a'.repeat(40), toVersion: '1.0.0.5', preparedAt: '2026-10-12T00:00:00.000Z', backendPath: 'backend.exe', recoveryRequired: false }, null, 2)
    fs.writeFileSync(markerPath, before, 'utf8')
    const rename = vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('injected atomic replace failure') })
    try {
      const { markPreparedRollbackRecoveryRequired, cancelPreparedRollback } = await import('./rollback.js')
      expect(() => markPreparedRollbackRecoveryRequired()).toThrow(/injected atomic replace failure/)
      expect(fs.readFileSync(markerPath, 'utf8')).toBe(before)
      const temporary = fs.readdirSync(electronMocks.__userDataDir).find(name => name.startsWith('rollback-marker.json.') && name.endsWith('.tmp'))
      expect(temporary).toBeDefined()
      expect(JSON.parse(fs.readFileSync(path.join(electronMocks.__userDataDir, temporary!), 'utf8')).recoveryRequired).toBe(true)
      cancelPreparedRollback()
      expect(fs.readFileSync(markerPath, 'utf8')).toBe(before)
      expect(fs.readdirSync(electronMocks.__userDataDir).some(name => name.startsWith('rollback-marker.json.') && name.endsWith('.tmp'))).toBe(true)
    } finally {
      rename.mockRestore()
      for (const name of fs.readdirSync(electronMocks.__userDataDir)) {
        if (name.startsWith('rollback-marker.json.') && name.endsWith('.tmp')) fs.unlinkSync(path.join(electronMocks.__userDataDir, name))
      }
      cleanup()
    }
  })
})

describe('rollback — prepareRollback hygiene and nesting guards', () => {
  it('clears a stale applied marker when preparing a new rollback', async () => {
    const cleanup = setupPackagedBackend()
    try {
      fs.writeFileSync(
        path.join(electronMocks.__userDataDir, 'rollback-applied.json'),
        JSON.stringify({ appliedAt: 'x', reason: 'old', fromVersion: 'a', toVersion: 'b' }),
      )
      const { prepareRollback, checkRollbackApplied } = await import('./rollback.js')
      await prepareRollback('10.3.0')
      expect(checkRollbackApplied()).toBeNull()
    } finally {
      cleanup()
    }
  })

  windowsIt('rejects install directory nested inside the backup root', async () => {
    electronMocks.app.isPackaged = true
    const backupRoot = path.join(electronMocks.__userDataDir, 'rollback', 'windows-app-current')
    const installDir = path.join(backupRoot, 'app')
    fs.mkdirSync(path.join(installDir, 'backend'), { recursive: true })
    fs.writeFileSync(path.join(installDir, 'backend', 'xcagi-backend.exe'), 'fake')
    fs.writeFileSync(path.join(installDir, 'XCAGI.exe'), 'fake-app')
    electronMocks.__state.exePath = path.join(installDir, 'XCAGI.exe')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = installDir
    try {
      const { prepareRollback } = await import('./rollback.js')
      await expect(prepareRollback('10.3.1')).rejects.toThrow(/互相嵌套/)
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
    }
  })

  windowsIt('rejects when the packaged app executable is missing', async () => {
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-noapp-${Date.now()}`)
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    fs.writeFileSync(path.join(backendDir, 'xcagi-backend.exe'), 'fake')
    electronMocks.__state.exePath = path.join(tmpResources, 'missing', 'XCAGI.exe')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      const { prepareRollback } = await import('./rollback.js')
      await expect(prepareRollback('10.3.2')).rejects.toThrow(/找不到当前 XCAGI 可执行文件/)
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
      fs.rmSync(tmpResources, { recursive: true, force: true })
    }
  })
})

describe('rollback — triggerRollback defensive paths', () => {
  function writeMarker(marker: Record<string, unknown>): void {
    fs.writeFileSync(
      path.join(electronMocks.__userDataDir, 'rollback-marker.json'),
      JSON.stringify(marker, null, 2),
      'utf8',
    )
  }

  it('rejects invalid rollback markers', async () => {
    const { triggerRollback } = await import('./rollback.js')
    const cases: Array<[Record<string, unknown>, string, RegExp]> = [
      [{ mode: 'backend', backendPath: '/tmp/xcagi-escape/backend/app', backupRelPath: '../../escape' }, 'escape', /路径越界/],
      [{ mode: 'backend', backendPath: '/tmp/xcagi-missing/backend/app' }, 'missing path', /缺少 backend 备份路径/],
      [{ mode: 'backend', backendPath: '/tmp/xcagi-gone/backend/app', backupRelPath: 'backend-gone' }, 'missing backup', /备份目录不存在/],
      [{ mode: 'windows-full', backendPath: '/tmp/xcagi-win/backend/app.exe', appPath: '/tmp/xcagi-win/app.exe', appBackupRelPath: 'windows-app-current' }, 'windows backup', process.platform === 'win32' ? /完整应用备份目录不存在/ : process.platform === 'darwin' ? /完整旧版应用/ : /缺少 backend 备份路径/],
    ]
    for (const [fields, reason, expected] of cases) {
      writeMarker({ fromVersion: '1.0.0', toVersion: '2.0.0', preparedAt: new Date().toISOString(), ...fields })
      await expect(triggerRollback(reason)).rejects.toThrow(expected)
    }
  })

  windowsOnly('admits the C# manual installer owned-state marker and retains its backup after health commit', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const userData = electronMocks.__userDataDir
      const rollbackRoot = path.join(userData, 'rollback')
      const appBackupRoot = path.join(rollbackRoot, 'windows-app-current')
      const ownedBackupRoot = path.join(rollbackRoot, 'manual-6a7a6f47-472a-4b3b-95ae-50f840324be5', 'owned')
      const manifestPath = path.join(ownedBackupRoot, 'mods', 'northwind', 'manifest.json')
      const manifestBytes = Buffer.from('{"id":"northwind","version":"2.3.0"}')
      fs.mkdirSync(path.dirname(manifestPath), { recursive: true })
      fs.mkdirSync(appBackupRoot, { recursive: true })
      fs.writeFileSync(manifestPath, manifestBytes)
      fs.writeFileSync(path.join(appBackupRoot, 'XCAGI.exe'), 'old-app')
      const expectedOwnedFiles = {
        'mods\\northwind\\manifest.json': createHash('sha256').update(manifestBytes).digest('hex'),
      }
      const marker = {
        mode: 'windows-full',
        fromVersion: '2.3.0',
        toVersion: '2.4.0',
        preparedAt: '2026-10-12T00:00:00.000Z',
        appPath: electronMocks.__state.exePath,
        backendPath: path.join(path.dirname(electronMocks.__state.exePath), 'backend', 'xcagi-backend.exe'),
        appBackupRelPath: 'windows-app-current',
        ownedUserDataRoot: userData,
        ownedBackupRoot,
        expectedOwnedFiles,
        expectedOwnedDirectories: ['mods', 'mods\\northwind'],
        expectedAppFiles: {},
      }
      writeMarker(marker)
      const { triggerRollback, commitRollback } = await import('./rollback.js')
      await expect(triggerRollback('synthetic C# manual marker')).resolves.toEqual({ mode: 'windows-full', scheduled: true })
      expect(windowsRollbackMocks.launchWindowsFullRollback).toHaveBeenCalledOnce()
      commitRollback()
      expect(fs.existsSync(path.join(userData, 'rollback-marker.json'))).toBe(false)
      expect(fs.readFileSync(manifestPath)).toEqual(manifestBytes)
    } finally {
      cleanup()
    }
  })

  it('restores the backend directory including nested files', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const resourcesPath = (process as { resourcesPath?: string }).resourcesPath as string
      const backendDir = path.join(resourcesPath, 'backend')
      const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
      fs.mkdirSync(path.join(backendDir, '_internal'), { recursive: true })
      fs.writeFileSync(path.join(backendDir, '_internal', 'data.txt'), 'original')

      const { prepareRollback, triggerRollback, checkRollbackApplied } = await import('./rollback.js')
      await prepareRollback('10.4.0')
      fs.writeFileSync(path.join(backendDir, exeName), 'broken')
      fs.rmSync(path.join(backendDir, '_internal'), { recursive: true, force: true })

      const result = await triggerRollback('health timeout')
      if (process.platform === 'win32') {
        expect(result).toEqual({ mode: 'windows-full', scheduled: true })
      } else if (process.platform === 'darwin') {
        expect(result).toEqual({ mode: 'macos-full', scheduled: true })
        expect(macosRollbackMocks.launchMacOSFullRollback).toHaveBeenCalled()
      } else {
        expect(result).toEqual({ mode: 'backend', scheduled: false })
        expect(fs.readFileSync(path.join(backendDir, exeName), 'utf8')).toBe('fake-backend')
        expect(fs.readFileSync(path.join(backendDir, '_internal', 'data.txt'), 'utf8')).toBe('original')
        const applied = checkRollbackApplied()
        expect(applied?.fromVersion).toBe('10.4.0')
        expect(applied?.toVersion).toBe('10.0.0')
      }
    } finally {
      cleanup()
    }
  })
})

const macIt = process.platform === 'darwin' ? it : it.skip
macIt.each([{ mode: 'backend' }, { mode: 'windows-full' }, { mode: 'macos-full' }, { mode: 'macos-full', appBundlePath: '/Applications/XCAGI.app' }, { mode: 'macos-full', appBackupRelPath: 'legacy-backend' }])('never mixes a legacy or invalid Mac marker %j with the new app or database', async (fields) => {
  const cleanup = setupPackagedBackend()
  const data = electronMocks.__userDataDir
  const resources = (process as { resourcesPath?: string }).resourcesPath as string
  const backup = path.join(data, 'rollback', 'legacy-backend')
  const database = path.join(data, 'data', 'xcagi.db')
  fs.mkdirSync(backup, { recursive: true })
  fs.mkdirSync(path.dirname(database), { recursive: true })
  fs.writeFileSync(path.join(backup, 'xcagi-backend'), 'old-backend')
  fs.writeFileSync(database, 'new-database')
  fs.writeFileSync(database + '.before', 'old-database')
  fs.writeFileSync(path.join(data, 'rollback-marker.json'), JSON.stringify({
    ...fields, fromVersion: '1.0.0+280225ac77ce', toVersion: '1.0.0.5',
    preparedAt: new Date().toISOString(), backendPath: path.join(resources, 'backend', 'xcagi-backend'),
    backupRelPath: 'legacy-backend', databasePath: database, databaseBackupPath: database + '.before',
  }))
  try {
    const { triggerRollback } = await import('./rollback.js')
    const originalApp = fs.readFileSync(electronMocks.__state.exePath)
    const originalMarker = fs.readFileSync(path.join(data, 'rollback-marker.json'), 'utf8')
    await expect(triggerRollback('legacy startup failed')).rejects.toThrow(/完整旧版应用/)
    expect(fs.readFileSync(path.join(resources, 'backend', 'xcagi-backend'), 'utf8')).toBe('fake-backend')
    expect(fs.readFileSync(database, 'utf8')).toBe('new-database')
    expect(fs.readFileSync(electronMocks.__state.exePath)).toEqual(originalApp)
    expect(fs.readFileSync(path.join(data, 'rollback-marker.json'), 'utf8')).toBe(originalMarker)
  } finally { cleanup() }
})
