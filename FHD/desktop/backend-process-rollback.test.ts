import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const ports = vi.hoisted(() => ({
  userData: '',
  spawn: vi.fn(),
  available: vi.fn(),
  terminate: vi.fn(),
  handoff: vi.fn(),
  pending: vi.fn(),
  rollback: vi.fn(),
  restore: vi.fn(),
  log: { write: vi.fn(), end: vi.fn() },
}))

vi.mock('electron', () => ({
  app: { isPackaged: false, isQuitting: false, getPath: () => ports.userData, quit: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
  dialog: { showMessageBox: vi.fn() },
}))
vi.mock('node:child_process', () => ({ spawn: ports.spawn, execFile: vi.fn(), execFileSync: vi.fn() }))
vi.mock('./desktop-config', () => ({
  APP_NAME: 'XCAGI', DEFAULT_PORT: 17500, DESKTOP_BACKEND_BIND_HOST: '127.0.0.1',
  backendEditionEnv: () => ({}),
  backendExecutable: () => ({ command: 'inert-test-backend', args: ['--desktop'], cwd: ports.userData }),
  isPortAvailable: ports.available,
  packagedBackendCandidates: () => [], portOccupiedHint: () => '',
  readPackagedProductSku: () => '', repoRoot: () => ports.userData,
}))
vi.mock('./backend-lifecycle', async importOriginal => ({
  ...await importOriginal<typeof import('./backend-lifecycle')>(),
  terminateChildProcess: ports.terminate,
}))
vi.mock('./model-usage-rollback', async importOriginal => ({
  ...await importOriginal<typeof import('./model-usage-rollback')>(),
  handoffModelUsageLedger: ports.handoff,
}))
vi.mock('./rollback', () => ({
  checkPendingRollback: ports.pending, triggerRollback: ports.rollback,
  prepareRollback: vi.fn(), cancelPreparedRollback: vi.fn(),
  attachDatabaseBackupToRollback: vi.fn(), clearPreparedRollbackRecoveryRequired: vi.fn(),
  markPreparedRollbackRecoveryRequired: vi.fn(),
}))
vi.mock('./desktop-resilience', () => ({ createForceUpgradeHandler: vi.fn() }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('backend stop and rollback writer exclusion', () => {
  let backend: typeof import('./backend-process')
  let child: EventEmitter

  beforeEach(async () => {
    vi.useFakeTimers()
    vi.resetModules()
    ports.userData = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-rollback-lifecycle-'))
    vi.spyOn(fs, 'createWriteStream').mockReturnValue(ports.log as never)
    ports.available.mockReset().mockResolvedValue(true)
    ports.terminate.mockReset().mockResolvedValue('terminated')
    ports.handoff.mockReset().mockResolvedValue(undefined)
    ports.pending.mockReset().mockReturnValue({ mode: 'windows-full' })
    ports.rollback.mockReset().mockImplementation(async (_reason, beforeRestore) => {
      await beforeRestore()
      ports.restore()
      return { mode: 'windows-full', scheduled: true }
    })
    child = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter() })
    ports.spawn.mockReset().mockReturnValue(child)
    backend = await import('./backend-process.js')
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    fs.rmSync(ports.userData, { recursive: true, force: true })
  })

  it('makes reentrant stop and rollback await the same actual child exit', async () => {
    await backend.startBackend()
    const exit = deferred<string>()
    ports.terminate.mockReturnValue(exit.promise)
    const first = backend.stopBackend()
    const second = backend.stopBackend()
    let stopped = false
    void second.then(() => { stopped = true })
    const rollback = backend.triggerRollbackSafe('test concurrent stop')
    await Promise.resolve()
    await Promise.resolve()

    expect(stopped).toBe(false)
    expect(ports.terminate).toHaveBeenCalledOnce()
    expect(ports.handoff).not.toHaveBeenCalled()
    expect(ports.restore).not.toHaveBeenCalled()
    exit.resolve('terminated')
    await Promise.all([first, second, rollback])
    expect(stopped).toBe(true)
    expect(ports.handoff).toHaveBeenCalledOnce()
    expect(ports.restore).toHaveBeenCalledOnce()
  })

  it('does not spawn after an outstanding port probe resumes during handoff', async () => {
    const available = deferred<boolean>()
    const handoff = deferred<void>()
    ports.available.mockReturnValue(available.promise)
    ports.handoff.mockReturnValue(handoff.promise)
    const starting = backend.startBackend()
    expect(ports.available).toHaveBeenCalledOnce()
    const rollback = backend.triggerRollbackSafe('test outstanding probe')
    await vi.waitFor(() => expect(ports.handoff).toHaveBeenCalledOnce())

    available.resolve(true)
    await starting
    expect(ports.spawn).not.toHaveBeenCalled()
    handoff.resolve(undefined)
    await rollback
  })

  it('keeps a scheduled full rollback stopped across queued and direct restarts', async () => {
    await backend.startBackend()
    await vi.advanceTimersByTimeAsync(10_000)
    child.emit('exit', 1) // A normal crash has already queued the 1.5-second restart.
    await expect(backend.triggerRollbackSafe('test scheduled rollback')).resolves.toEqual({
      mode: 'windows-full', scheduled: true,
    })
    await vi.advanceTimersByTimeAsync(5_000)
    await backend.startBackend()
    child.emit('exit', 1) // A late exit notification must not arm another restart.
    await vi.advanceTimersByTimeAsync(5_000)

    expect(ports.spawn).toHaveBeenCalledOnce()
    expect(ports.available).toHaveBeenCalledOnce()
    expect(ports.handoff).toHaveBeenCalledOnce()
  })

  it('retains the live writer and aborts handoff when child termination times out', async () => {
    await backend.startBackend()
    ports.terminate.mockResolvedValue('kill-timeout')
    await expect(backend.triggerRollbackSafe('test stop timeout')).resolves.toBeNull()
    expect(ports.handoff).not.toHaveBeenCalled()
    expect(ports.restore).not.toHaveBeenCalled()
    const { desktopRuntime } = await import('./runtime-state.js')
    expect(desktopRuntime.backendProcess).toBe(child)
  })

  it('leaves real rollback files and the marker intact when ledger handoff fails', async () => {
    const rollback = await vi.importActual<typeof import('./rollback')>('./rollback')
    ports.pending.mockImplementation(rollback.checkPendingRollback)
    ports.rollback.mockImplementation(rollback.triggerRollback)
    const active = path.join(ports.userData, 'active-backend')
    const backup = path.join(ports.userData, 'rollback', 'backend-old')
    fs.mkdirSync(active, { recursive: true })
    fs.mkdirSync(backup, { recursive: true })
    fs.writeFileSync(path.join(active, 'version.txt'), 'new runtime')
    fs.writeFileSync(path.join(backup, 'version.txt'), 'old runtime')
    const marker = path.join(ports.userData, 'rollback-marker.json')
    fs.writeFileSync(marker, JSON.stringify({
      mode: process.platform === 'darwin' ? 'macos-full' : 'backend',
      fromVersion: '1.0.0', toVersion: '1.0.1', preparedAt: '2026-10-29T00:00:00Z',
      backendPath: path.join(active, 'backend'), backupRelPath: 'backend-old',
      appBundlePath: active, appBackupRelPath: 'backend-old',
    }))
    ports.handoff.mockRejectedValue(new Error('pending debit prevents ledger handoff'))

    await expect(backend.triggerRollbackSafe('test pending debit')).resolves.toBeNull()
    expect(ports.handoff).toHaveBeenCalledOnce()
    expect(fs.readFileSync(path.join(active, 'version.txt'), 'utf8')).toBe('new runtime')
    expect(fs.readFileSync(path.join(backup, 'version.txt'), 'utf8')).toBe('old runtime')
    expect(fs.existsSync(marker)).toBe(true)
    expect(fs.existsSync(path.join(ports.userData, 'rollback-applied.json'))).toBe(false)
  })

  it.each(['mods/billing/ledger.json', 'data/ledger.db'])(
    'blocks a Windows owned snapshot from overwriting %s before handoff', async relative => {
      const rollback = await vi.importActual<typeof import('./rollback')>('./rollback')
      const ledger = path.join(ports.userData, relative)
      const active = path.join(ports.userData, 'installation')
      fs.mkdirSync(path.dirname(ledger), { recursive: true })
      fs.mkdirSync(active)
      const json = '{"entries":[],"wallets":{"u":{"balance_units":73}}}'
      const database = Buffer.from('current SQLite bytes must remain untouched')
      fs.writeFileSync(ledger, json)
      fs.writeFileSync(`${ledger}.sqlite3`, database)
      const marker = path.join(ports.userData, 'rollback-marker.json')
      const recovery = JSON.stringify({
        mode: 'windows-full', fromVersion: '1.0.0', toVersion: '1.0.1',
        backendPath: path.join(active, 'backend', 'backend.exe'),
        appPath: path.join(active, 'XCAGI.exe'), appBackupRelPath: 'app-old',
        ownedUserDataRoot: ports.userData,
      })
      fs.writeFileSync(marker, recovery)
      const platform = Object.getOwnPropertyDescriptor(process, 'platform')!
      vi.stubEnv('MODEL_USAGE_LEDGER_PATH', ledger)
      try {
        // Only branch selection changes: real paths/files remain local and no helper is launched.
        Object.defineProperty(process, 'platform', { ...platform, value: 'win32' })
        await expect(rollback.triggerRollback('test owned ledger', ports.handoff))
          .rejects.toThrow(/Mod\/数据库快照/)
      } finally {
        Object.defineProperty(process, 'platform', platform)
        vi.unstubAllEnvs()
      }
      expect(ports.handoff).not.toHaveBeenCalled()
      expect(fs.readFileSync(ledger, 'utf8')).toBe(json)
      expect(fs.readFileSync(`${ledger}.sqlite3`)).toEqual(database)
      expect(fs.readFileSync(marker, 'utf8')).toBe(recovery)
    },
  )
})
