import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { executeDesktopControl } from './aiopenDesktopControls'

afterEach(() => vi.unstubAllGlobals())

function bridge() {
  const api = {
    getAppIdentity: vi.fn().mockResolvedValue({ version: '1.2', install: { buildSha: 'abc' } }),
    getUpdateStatus: vi.fn().mockResolvedValue({ type: 'update-not-available' }),
    getAutoLaunch: vi.fn().mockResolvedValue(false),
    setAutoLaunch: vi.fn().mockResolvedValue({ ok: true }),
    checkForUpdates: vi.fn().mockResolvedValue({ updateInfo: { version: '2' } }),
    downloadUpdate: vi.fn().mockResolvedValue(['download.zip']),
    installUpdate: vi.fn().mockResolvedValue(undefined),
  }
  vi.stubGlobal('xcagiDesktop', api)
  return api
}

describe('native screen commands', () => {
  it('uses the shipped preload functions and exact IPC channels', async () => {
    const invoke = vi.fn(async (channel: string) => {
      if (channel === 'xcagi:get-app-identity') return { version: 'installed-version' }
      if (channel === 'xcagi:get-auto-launch') return true
      if (channel === 'xcagi:get-update-observation') return { type: 'update-not-available', observedAt: 'now' }
      throw new Error(`unexpected IPC ${channel}`)
    })
    const electron = {
      ipcRenderer: { invoke },
      contextBridge: { exposeInMainWorld: (name: string, api: unknown) => vi.stubGlobal(name, api) },
    }
    const code = ts.transpileModule(readFileSync(resolve(process.cwd(), '../desktop/preload.ts'), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText
    runInNewContext(code, { exports: {}, require: () => electron, process: { platform: 'darwin', versions: {} }, window: { addEventListener: vi.fn() } })
    expect(await executeDesktopControl('desktop_info', {}, () => {})).toMatchObject({ success: true, auto_launch: true, identity: { version: 'installed-version' } })
    expect(invoke.mock.calls.map(([channel]) => channel)).toEqual(['xcagi:get-app-identity', 'xcagi:get-update-observation', 'xcagi:get-auto-launch'])
  })
  it('reads actual native state and rejects browser windows', async () => {
    vi.stubGlobal('xcagiDesktop', undefined)
    expect((await executeDesktopControl('desktop_info', {}, () => {})).code).toBe('DESKTOP_REQUIRED')
    bridge()
    const result = await executeDesktopControl('desktop_info', {}, () => {})
    expect(result).toMatchObject({ success: true, auto_launch: false, identity: { version: '1.2' } })
  })
  it('requires boolean state, reads back the setting and preserves native rejection', async () => {
    const api = bridge()
    await expect(executeDesktopControl('desktop_auto_launch', { enabled: 'false' }, () => {})).rejects.toThrow()
    expect(api.setAutoLaunch).not.toHaveBeenCalled()
    expect((await executeDesktopControl('desktop_auto_launch', { enabled: true }, () => {})).success).toBe(false)
    api.getAutoLaunch.mockResolvedValue(true)
    expect((await executeDesktopControl('desktop_auto_launch', { enabled: true }, () => {})).success).toBe(true)
    api.setAutoLaunch.mockResolvedValue({ ok: false })
    expect((await executeDesktopControl('desktop_auto_launch', { enabled: true }, () => {})).success).toBe(false)
  })
  it.each(['check', 'download', 'install'])('submits %s but requires follow-up verification', async operation => {
    bridge()
    expect(await executeDesktopControl('desktop_update', { operation }, () => {})).toMatchObject({ success: true, operation, requires_followup: true, verification: 'native_request_returned' })
  })
  it('does not publish results or continue after an account change', async () => {
    const api = bridge()
    let current = true
    api.getAppIdentity.mockImplementation(async () => { current = false; return {} })
    await expect(executeDesktopControl('desktop_info', {}, () => { if (!current) throw new Error('stale') })).rejects.toThrow('stale')
    expect(api.getUpdateStatus).not.toHaveBeenCalled()
  })
  it('does not treat rejected updates as successful', async () => {
    const api = bridge()
    api.downloadUpdate.mockRejectedValue(new Error('download failed'))
    await expect(executeDesktopControl('desktop_update', { operation: 'download' }, () => {})).rejects.toThrow('download failed')
    await expect(executeDesktopControl('desktop_update', { operation: 'secureGet' }, () => {})).rejects.toThrow()
  })
  it('reports skipped checks as not executed and marks legacy status incomplete', async () => {
    const api = bridge()
    api.checkForUpdates.mockResolvedValue({ skipped: true, reason: 'dev-mode' })
    expect(await executeDesktopControl('desktop_update', { operation: 'check' }, () => {})).toMatchObject({ success: false, code: 'UPDATE_SKIPPED', verification: 'not_executed' })
    expect(await executeDesktopControl('desktop_info', {}, () => {})).toMatchObject({ update: { observation_complete: false } })
  })
})
