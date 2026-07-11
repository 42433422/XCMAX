import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const updaterSession = {
    setProxy: vi.fn<() => Promise<void>>(),
  }
  const autoUpdater = Object.defineProperty({}, 'netSession', {
    configurable: false,
    enumerable: true,
    get: () => updaterSession,
  })
  return { autoUpdater, updaterSession }
})

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => '/tmp/xcagi-test'),
    getVersion: vi.fn(() => '10.0.0'),
    isPackaged: false,
  },
  dialog: {},
  net: {},
  session: {
    defaultSession: {},
  },
}))

vi.mock('electron-updater', () => ({ autoUpdater: mocks.autoUpdater }))

describe('updater session ownership', () => {
  beforeEach(() => {
    vi.resetModules()
    mocks.updaterSession.setProxy.mockReset().mockResolvedValue(undefined)
  })

  it('configures the getter-only electron-updater session without assigning it', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(mocks.autoUpdater, 'netSession')
    expect(descriptor?.get).toBeTypeOf('function')
    expect(descriptor?.set).toBeUndefined()

    const { ensureUpdaterNetSession } = await import('./updater.js')
    await expect(ensureUpdaterNetSession()).resolves.toBe(mocks.updaterSession)
    expect(mocks.updaterSession.setProxy).toHaveBeenCalledOnce()
    expect(mocks.updaterSession.setProxy).toHaveBeenCalledWith({ mode: 'direct' })
  })

  it('clears a failed initialization so the next update check can retry', async () => {
    mocks.updaterSession.setProxy
      .mockRejectedValueOnce(new Error('temporary session failure'))
      .mockResolvedValueOnce(undefined)

    const { ensureUpdaterNetSession } = await import('./updater.js')
    await expect(ensureUpdaterNetSession()).rejects.toThrow('temporary session failure')
    await expect(ensureUpdaterNetSession()).resolves.toBe(mocks.updaterSession)
    expect(mocks.updaterSession.setProxy).toHaveBeenCalledTimes(2)
  })
})
