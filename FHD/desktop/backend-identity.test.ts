import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  userData: '',
  packaged: true,
  spawn: vi.fn(),
}))

vi.mock('electron', () => ({
  app: {
    get isPackaged() { return state.packaged },
    getPath: () => state.userData,
    getVersion: () => '1.0.0',
    isQuitting: false,
  },
  dialog: { showErrorBox: vi.fn() },
}))
vi.mock('node:child_process', () => ({ spawn: state.spawn, execFile: vi.fn() }))
vi.mock('./desktop-config', async importOriginal => ({
  ...await importOriginal<typeof import('./desktop-config')>(),
  isPortAvailable: vi.fn(async () => true),
}))
vi.mock('./rollback', () => ({
  prepareRollback: vi.fn(async () => undefined),
  cancelPreparedRollback: vi.fn(),
  attachDatabaseBackupToRollback: vi.fn(),
  triggerRollback: vi.fn(),
}))
vi.mock('./desktop-resilience', () => ({ createForceUpgradeHandler: vi.fn() }))

import { desktopBackendEnv } from './backend-env'
import { startBackend, runBackendMigrationWithRollback } from './backend-process'
import { desktopRuntime } from './runtime-state'

describe('packaged backend build identity resource handoff', () => {
  let root: string
  let resources: string
  let originalResources: PropertyDescriptor | undefined

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-build-identity-'))
    resources = path.join(root, 'XCAGI.app', 'Contents', 'Resources')
    state.userData = path.join(root, 'user-data')
    state.packaged = true
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
    Object.defineProperty(process, 'resourcesPath', { value: resources, configurable: true })
    state.spawn.mockImplementation((_command: string, args: string[]) => {
      const child = Object.assign(new EventEmitter(), {
        stdout: new EventEmitter(), stderr: new EventEmitter(), kill: vi.fn(),
      })
      if (args.includes('--migrate-only')) queueMicrotask(() => child.emit('exit', 0))
      return child
    })
  })

  afterEach(async () => {
    desktopRuntime.backendProcess = null
    const stream = desktopRuntime.backendLogStream
    desktopRuntime.backendLogStream = null
    if (stream) {
      await new Promise<void>(resolve => { stream.once('close', resolve); stream.end() })
    }
    if (originalResources) Object.defineProperty(process, 'resourcesPath', originalResources)
    else Reflect.deleteProperty(process, 'resourcesPath')
    vi.unstubAllEnvs()
    fs.rmSync(root, { recursive: true, force: true })
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
  })

  it('hands the same Resources to the actual migration spawn', async () => {
    await runBackendMigrationWithRollback('1.0.0.1')
    expect(state.spawn).toHaveBeenCalledTimes(1)
    expect(state.spawn.mock.calls[0][1]).toContain('--migrate-only')
    expect(state.spawn.mock.calls[0][2].env.XCAGI_DESKTOP_RESOURCES).toBe(resources)
  })
})
