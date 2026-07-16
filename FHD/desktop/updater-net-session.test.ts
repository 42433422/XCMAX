import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const updaterSession = {
    setProxy: vi.fn(() => Promise.resolve()),
  }
  const autoUpdater = Object.defineProperty({}, 'netSession', {
    configurable: false,
    enumerable: true,
    get: vi.fn(() => updaterSession),
  })
  return { autoUpdater, updaterSession }
})

vi.mock('electron', () => ({
  app: { getPath: vi.fn(() => '/tmp') },
  dialog: {},
  net: {},
  session: { defaultSession: {} },
}))
vi.mock('electron-updater', () => ({ autoUpdater: mocks.autoUpdater }))

describe('updater — dedicated network session', () => {
  it('configures electron-updater 6.x read-only netSession in place', async () => {
    const { ensureUpdaterNetSession } = await import('./updater.js')

    await expect(ensureUpdaterNetSession()).resolves.toBe(mocks.updaterSession)
    expect(Reflect.getOwnPropertyDescriptor(mocks.autoUpdater, 'netSession')?.set).toBeUndefined()
    expect(Reflect.getOwnPropertyDescriptor(mocks.autoUpdater, 'netSession')?.get).toHaveBeenCalledOnce()
    expect(mocks.updaterSession.setProxy).toHaveBeenCalledOnce()
    expect(mocks.updaterSession.setProxy).toHaveBeenCalledWith({ mode: 'direct' })
  })
})
