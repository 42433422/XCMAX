import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHmac } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  userData: '',
  packaged: true,
  spawn: vi.fn(),
  lifecycle: [] as string[],
}))

vi.mock('electron', () => ({
  app: {
    get isPackaged() { return state.packaged },
    getPath: () => state.userData,
    getVersion: () => '1.0.0',
    isQuitting: false,
    quit: vi.fn(),
  },
  // 提示必须挂到窗口上：macOS 上无窗口的 showMessageBox 会以 NSAlert.runModal 阻塞主进程。
  BrowserWindow: { getAllWindows: () => [{ isDestroyed: () => false }] },
  dialog: { showErrorBox: vi.fn(), showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })) },
}))
vi.mock('node:child_process', () => ({ spawn: state.spawn, execFile: vi.fn() }))
vi.mock('./desktop-config', async importOriginal => ({
  ...await importOriginal<typeof import('./desktop-config')>(),
  isPortAvailable: vi.fn(async () => true),
}))
vi.mock('./rollback', () => ({
  prepareRollback: vi.fn(async () => undefined),
  markPreparedRollbackRecoveryRequired: vi.fn(() => state.lifecycle.push('intent')),
  clearPreparedRollbackRecoveryRequired: vi.fn(() => state.lifecycle.push('clear')),
  cancelPreparedRollback: vi.fn(),
  attachDatabaseBackupToRollback: vi.fn(),
  triggerRollback: vi.fn(),
}))
vi.mock('./desktop-resilience', () => ({ createForceUpgradeHandler: vi.fn() }))

import { desktopBackendChallenge, desktopBackendEnv, desktopWorkspaceToken } from './backend-env'
import { startBackend, stopBackend, waitForBackendPing, startBackendHealthWatchdog, stopBackendHealthWatchdog, setBackendHealthNotifier, runBackendMigrationWithRollback } from './backend-process'
import { desktopRuntime, hasVerifiedDesktopBackend } from './runtime-state'
import * as loopback from './backend-loopback-http'
import { markPreparedRollbackRecoveryRequired, clearPreparedRollbackRecoveryRequired } from './rollback'

describe('packaged backend build identity resource handoff', () => {
  let root: string
  let resources: string
  let originalResources: PropertyDescriptor | undefined
  let originalDefaultApp: PropertyDescriptor | undefined

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-build-identity-'))
    resources = path.join(root, 'XCAGI.app', 'Contents', 'Resources')
    state.userData = path.join(root, 'user-data')
    state.packaged = true
    state.lifecycle.length = 0
    fs.mkdirSync(path.join(resources, 'backend'), { recursive: true })
    fs.mkdirSync(state.userData)
    fs.writeFileSync(path.join(resources, 'build-info.json'), JSON.stringify({
      schema_version: 1,
      gitSha: '70da5cdf6ca18abc44eb5370734314ca6663fb8f',
      version: '1.0.0.1',
      releaseId: 'xcagi-1.0.0.1-70da5cdf6ca18abc44eb5370734314ca6663fb8f',
      builtAt: '2026-09-05T12:00:00.000Z',
    }))
    const binary = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(resources, 'backend', binary), 'inert fixture; never executed')
    originalResources = Object.getOwnPropertyDescriptor(process, 'resourcesPath')
    originalDefaultApp = Object.getOwnPropertyDescriptor(process, 'defaultApp')
    Object.defineProperty(process, 'resourcesPath', { value: resources, configurable: true })
    state.spawn.mockImplementation((_command: string, args: string[]) => {
      const child = Object.assign(new EventEmitter(), {
        stdout: new EventEmitter(), stderr: new EventEmitter(), kill: vi.fn(),
        pid: 123, exitCode: null, signalCode: null,
      })
      if (args.includes('--migrate-only')) {
        state.lifecycle.push('spawn')
        queueMicrotask(() => child.emit('exit', 0))
      }
      return child
    })
  })

  afterEach(async () => {
    stopBackendHealthWatchdog()
    setBackendHealthNotifier(null)
    desktopRuntime.backendProcess = null
    desktopRuntime.verifiedBackendProcess = null
    await stopBackend()
    vi.useRealTimers()
    const stream = desktopRuntime.backendLogStream
    desktopRuntime.backendLogStream = null
    if (stream) {
      await new Promise<void>(resolve => { stream.once('close', resolve); stream.end() })
    }
    if (originalResources) Object.defineProperty(process, 'resourcesPath', originalResources)
    else Reflect.deleteProperty(process, 'resourcesPath')
    if (originalDefaultApp) Object.defineProperty(process, 'defaultApp', originalDefaultApp)
    else Reflect.deleteProperty(process, 'defaultApp')
    vi.unstubAllEnvs()
    fs.rmSync(root, { recursive: true, force: true })
  })

  function provenResponse(url: string) {
    const nonce = new URL(url).searchParams.get('desktop_challenge') || ''
    const proof = createHmac('sha256', desktopWorkspaceToken)
      .update(`xcagi-desktop-backend-v1:${nonce}`).digest('hex')
    return { ok: true, getHeader: (name: string) => name === 'server' ? 'uvicorn' : proof,
      json: async () => ({ pong: true }) }
  }

  it('requires the exact fresh nonce and a strict 64-character lowercase proof', () => {
    const first = desktopBackendChallenge()
    const second = desktopBackendChallenge()
    expect(first.nonce).toMatch(/^[0-9a-f]{64}$/)
    expect(second.nonce).not.toBe(first.nonce)
    const proof = provenResponse(`http://127.0.0.1/api/ping?desktop_challenge=${first.nonce}`).getHeader('x-xcagi-desktop-proof')
    expect(first.verify(proof)).toBe(true)
    expect(second.verify(proof)).toBe(false)
    for (const invalid of ['', '0'.repeat(64), proof.toUpperCase(), `${proof}\n`, ` ${proof}`, 'Ａ'.repeat(64)]) {
      expect(first.verify(invalid)).toBe(false)
    }
  })

  it('re-authenticates an automatic exit restart through the existing health tick without a manual readiness wait', async () => {
    vi.useFakeTimers()
    const requests: string[] = []
    vi.spyOn(loopback, 'loopbackHttpGet').mockImplementation(async url => {
      requests.push(url)
      return provenResponse(url)
    })
    const notify = vi.fn()
    setBackendHealthNotifier(notify)
    await startBackend()
    startBackendHealthWatchdog()
    await vi.advanceTimersByTimeAsync(20_000)
    const first = desktopRuntime.backendProcess!
    expect(hasVerifiedDesktopBackend()).toBe(true)
    Object.assign(first, { exitCode: 1 })
    first.emit('exit', 1)
    expect(hasVerifiedDesktopBackend()).toBe(false)
    await vi.advanceTimersByTimeAsync(1500)
    const replacement = desktopRuntime.backendProcess!
    expect(replacement).not.toBe(first)
    expect(hasVerifiedDesktopBackend()).toBe(false)
    await vi.advanceTimersByTimeAsync(18_500)
    expect(desktopRuntime.verifiedBackendProcess).toBe(replacement)
    expect(hasVerifiedDesktopBackend()).toBe(true)
    expect(notify).toHaveBeenLastCalledWith('ready')
    expect(new Set(requests).size).toBe(requests.length)
    expect(requests.some(url => url.includes(desktopWorkspaceToken))).toBe(false)
    const firstVerifiedAt = desktopRuntime.startupMarks.backendHealthMs
    await vi.advanceTimersByTimeAsync(20_000)
    expect(desktopRuntime.startupMarks.backendHealthMs).toBe(firstVerifiedAt)
  })

  it('keeps the watchdog armed when a restarted backend remains unresponsive', async () => {
    vi.useFakeTimers()
    let responsive = true
    vi.spyOn(loopback, 'loopbackHttpGet').mockImplementation(async url => {
      if (!responsive) throw new Error('backend has stopped answering ping')
      return provenResponse(url)
    })
    state.spawn.mockImplementation(() => {
      const child = Object.assign(new EventEmitter(), {
        stdout: new EventEmitter(), stderr: new EventEmitter(),
        kill: vi.fn(), pid: 123, exitCode: null as number | null, signalCode: null,
      })
      child.kill.mockImplementation(() => {
        queueMicrotask(() => { child.exitCode = 0; child.emit('exit', 0, null) })
        return true
      })
      return child
    })
    await startBackend()
    startBackendHealthWatchdog()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(hasVerifiedDesktopBackend()).toBe(true)
    responsive = false
    // 3 failures trigger the first restart; the replacement then fails the
    // 90-second readiness wait. The watchdog must still attempt another one.
    await vi.advanceTimersByTimeAsync(320_000)
    expect(state.spawn.mock.calls.length).toBeGreaterThanOrEqual(3)
  })

  it('does not let a late proof from the old child authorize or revoke its replacement', async () => {
    vi.useFakeTimers()
    let resolveOld!: (value: ReturnType<typeof provenResponse>) => void
    let oldUrl = ''
    vi.spyOn(loopback, 'loopbackHttpGet').mockImplementation(async url => {
      if (!oldUrl) { oldUrl = url; return new Promise(resolve => { resolveOld = resolve }) }
      return provenResponse(url)
    })
    await startBackend()
    const oldWait = waitForBackendPing(17500, 250).then(() => null, error => error)
    desktopRuntime.backendProcess = null
    await startBackend()
    const replacement = desktopRuntime.backendProcess!
    await waitForBackendPing(17500, 250)
    expect(desktopRuntime.verifiedBackendProcess).toBe(replacement)
    await vi.advanceTimersByTimeAsync(300)
    resolveOld(provenResponse(oldUrl))
    await vi.advanceTimersByTimeAsync(150)
    expect(await oldWait).toBeInstanceOf(Error)
    expect(desktopRuntime.verifiedBackendProcess).toBe(replacement)
  })

  it('revokes ownership on stop and ignores an in-flight successful proof after stopping', async () => {
    vi.useFakeTimers()
    let resolveProof!: (value: ReturnType<typeof provenResponse>) => void
    let requestUrl = ''
    vi.spyOn(loopback, 'loopbackHttpGet').mockImplementation(async url => {
      requestUrl = url
      return new Promise(resolve => { resolveProof = resolve })
    })
    await startBackend()
    const child = desktopRuntime.backendProcess!
    desktopRuntime.verifiedBackendProcess = child
    const waiting = waitForBackendPing(17500, 250).then(() => null, error => error)
    Object.assign(child, { exitCode: 0 })
    await stopBackend()
    expect(hasVerifiedDesktopBackend()).toBe(false)
    await vi.advanceTimersByTimeAsync(300)
    resolveProof(provenResponse(requestUrl))
    await vi.advanceTimersByTimeAsync(150)
    expect(await waiting).toBeInstanceOf(Error)
    expect(desktopRuntime.verifiedBackendProcess).toBeNull()
  })

  it('uses the real package resources and preserves explicit identity env without mutating input', () => {
    const input = { DATABASE_URL: 'must-not-inherit', XCAGI_GIT_SHA: 'explicit', XCAGI_DESKTOP_RESOURCES: '/stale' }
    const env = desktopBackendEnv(input, undefined, resources)
    expect(env.XCAGI_DESKTOP_RESOURCES).toBe(resources)
    expect(fs.existsSync(path.join(env.XCAGI_DESKTOP_RESOURCES!, 'build-info.json'))).toBe(true)
    expect(env.XCAGI_GIT_SHA).toBe('explicit')
    expect(env.DATABASE_URL).toBeUndefined()
    expect(input.DATABASE_URL).toBe('must-not-inherit')
    expect(input.XCAGI_DESKTOP_RESOURCES).toBe('/stale')
  })

  it('does not inject a checked-in build-info identity for development', () => {
    const env = desktopBackendEnv({}, path.join(root, 'FHD'))
    expect(env.XCAGI_DESKTOP_RESOURCES).toBeUndefined()
    expect(env.XCAGI_MODS_ROOT).toBe(path.join(root, 'FHD', 'mods'))
  })

  it('hands Resources to the actual packaged normal startup spawn', async () => {
    vi.stubEnv('XCAGI_DESKTOP_RESOURCES', '/stale-inherited-resources')
    await startBackend()
    expect(state.spawn).toHaveBeenCalledTimes(1)
    const options = state.spawn.mock.calls[0][2]
    expect(options.env.XCAGI_DESKTOP_RESOURCES).toBe(resources)
    expect(options.env.XCAGI_DATA_DIR).toBe(state.userData)
    expect(options.env.XCAGI_DESKTOP_RESOURCES).not.toBe(state.userData)
    expect(options.env.XCAGI_PARENT_PID).toBe(String(process.pid))
  })

  it('hands an unguessable process capability to every backend restart without logging or accepting an inherited value', async () => {
    vi.stubEnv('XCAGI_DESKTOP_WORKSPACE_TOKEN', 'inherited-public-value')
    await startBackend()
    const [command, args, first] = state.spawn.mock.calls[0]
    const token = first.env.XCAGI_DESKTOP_WORKSPACE_TOKEN
    expect(token).toMatch(/^[0-9a-f]{64}$/)
    expect(token).not.toBe(process.env.XCAGI_DESKTOP_WORKSPACE_TOKEN)
    expect(JSON.stringify([command, args])).not.toContain(token)
    desktopRuntime.backendProcess = null
    await startBackend()
    expect(state.spawn.mock.calls[1][2].env.XCAGI_DESKTOP_WORKSPACE_TOKEN).toBe(token)
    const stream = desktopRuntime.backendLogStream
    if (stream) await new Promise<void>(resolve => stream.write('', () => resolve()))
    for (const name of fs.readdirSync(path.join(state.userData, 'logs'))) {
      expect(fs.readFileSync(path.join(state.userData, 'logs', name), 'utf8')).not.toContain(token)
    }
  })

  it.each([
    { defaultApp: true, appPackaged: true, packaged: false },
    { defaultApp: true, appPackaged: false, packaged: false },
    { defaultApp: undefined, appPackaged: true, packaged: true },
    { defaultApp: undefined, appPackaged: false, packaged: false },
    { defaultApp: false, appPackaged: true, packaged: true },
    { defaultApp: false, appPackaged: false, packaged: false },
  ])('starts the correct backend with defaultApp=$defaultApp and app.isPackaged=$appPackaged', async ({ defaultApp, appPackaged, packaged }) => {
    Object.defineProperty(process, 'defaultApp', { value: defaultApp, configurable: true })
    state.packaged = appPackaged
    vi.stubEnv('PYTHON', 'python-from-test')
    const { isDesktopPackaged, repoRoot, readPackagedAppVersion } = await import('./desktop-config.js')
    const sourceRoot = path.resolve(__dirname, '..', '..')
    const binary = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'

    expect(isDesktopPackaged()).toBe(packaged)
    expect(repoRoot()).toBe(packaged ? resources : sourceRoot)
    expect(readPackagedAppVersion()).toBe(packaged ? '1.0.0.1' : 'dev')
    await startBackend()

    expect(state.spawn).toHaveBeenCalledOnce()
    const [command, args, options] = state.spawn.mock.calls[0]
    expect(command).toBe(packaged ? path.join(resources, 'backend', binary) : 'python-from-test')
    expect(args[0]).toBe(packaged ? '--desktop' : path.join(sourceRoot, 'XCAGI', 'run.py'))
    expect(args).toContain('--desktop')
    expect(options.cwd).toBe(packaged ? path.join(resources, 'backend') : sourceRoot)
    expect(options.env.XCAGI_DESKTOP_RESOURCES).toBe(packaged ? resources : undefined)
    expect(options.env.XCAGI_DATA_DIR).toBe(state.userData)
  })

  it('hands the same Resources to the actual migration spawn', async () => {
    await runBackendMigrationWithRollback('1.0.0.1')
    if (process.platform === 'win32') {
      expect(markPreparedRollbackRecoveryRequired).toHaveBeenCalledOnce()
      expect(clearPreparedRollbackRecoveryRequired).toHaveBeenCalledOnce()
      expect(state.lifecycle).toEqual(['intent', 'spawn', 'clear'])
    } else {
      expect(markPreparedRollbackRecoveryRequired).not.toHaveBeenCalled()
      expect(clearPreparedRollbackRecoveryRequired).not.toHaveBeenCalled()
      expect(state.lifecycle).toEqual(['spawn'])
    }
    expect(state.spawn).toHaveBeenCalledTimes(1)
    expect(state.spawn.mock.calls[0][1]).toContain('--migrate-only')
    expect(state.spawn.mock.calls[0][2].env.XCAGI_DESKTOP_RESOURCES).toBe(resources)
  })
})
