import { beforeEach, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  secret: vi.fn(() => 'synthetic-value'),
  query: vi.fn(),
  notification: { on: vi.fn(), show: vi.fn() },
}))
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: (...args: any[]) => any) => mocks.handlers.set(name, handler) },
  app: {}, clipboard: {}, shell: {},
  Notification: Object.assign(vi.fn(function () { return mocks.notification }), { isSupported: () => true }),
}))
vi.mock('./desktop-config', () => ({ APP_NAME: 'test', DEFAULT_PORT: 18500, readPackagedAppVersion: vi.fn() }))
vi.mock('./window-manager', () => ({ broadcastToRenderer: vi.fn() }))
vi.mock('./backend-process', () => ({ writeBackendLog: vi.fn(), stopBackend: vi.fn(), runBackendMigrationWithRollback: vi.fn() }))
vi.mock('./app-shell', () => ({}))
vi.mock('./updater', () => ({}))
vi.mock('./rollback', () => ({}))
vi.mock('./desktop-install-update', () => ({}))
vi.mock('./data-bridge', () => ({ desktopOfflineDbPath: () => '/synthetic/db' }))
vi.mock('./data-bridge-session', () => ({ queryOfflineForSession: mocks.query }))
vi.mock('./secure-store', () => ({ getSecret: mocks.secret }))
vi.mock('./desktop-resilience', () => ({}))

import { registerDesktopIpcHandlers } from './ipc-handlers'
import { desktopRuntime } from './runtime-state'

function sender(url: string): IpcMainInvokeEvent {
  const frame = { url }
  desktopRuntime.mainWindow = {
    isDestroyed: () => false,
    webContents: { id: 17, mainFrame: frame },
  } as unknown as NonNullable<typeof desktopRuntime.mainWindow>
  return { sender: { id: 17, session: {} }, senderFrame: frame } as unknown as IpcMainInvokeEvent
}

beforeEach(() => {
  mocks.handlers.clear()
  mocks.secret.mockClear()
  mocks.query.mockReset()
  desktopRuntime.splashUrl = 'file:///trusted/splash.html'
  registerDesktopIpcHandlers()
})

it.each(['http://127.0.0.1:17500/', 'file:///untrusted/splash.html'])(
  'all handlers reject an unauthorized main-document URL: %s', async (url) => {
    const event = sender(url)
    expect(mocks.handlers.size).toBeGreaterThan(20)
    for (const handler of mocks.handlers.values()) {
      expect(await handler(event)).toEqual({ ok: false, reason: 'untrusted_sender' })
    }
    expect(mocks.secret).not.toHaveBeenCalled()
    expect(mocks.query).not.toHaveBeenCalled()
  },
)

it.each(['http://127.0.0.1:18500/', 'file:///trusted/splash.html'])(
  'configured runtime and exact splash remain trusted: %s', async (url) => {
    expect(await mocks.handlers.get('xcagi:secure-get')!(sender(url), 'synthetic-key')).toBe('synthetic-value')
  },
)

it('offline result is rejected if the main frame navigates while awaiting data', async () => {
  const event = sender('http://127.0.0.1:18500/')
  let finish!: (value: unknown) => void
  mocks.query.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const result = mocks.handlers.get('xcagi:offline-query')!(event, { kind: 'products' })
  expect(mocks.query).toHaveBeenCalledOnce()
  ;(event.senderFrame as unknown as { url: string }).url = 'http://127.0.0.1:18501/'
  finish({ ok: true, rows: ['synthetic'] })
  expect(await result).toEqual({ ok: false, reason: 'untrusted_sender' })
})


it('trusted runtime can still show a native notification', async () => {
  const result = await mocks.handlers.get('xcagi:show-notification')!(
    sender('http://127.0.0.1:18500/'), { title: 'Synthetic', body: 'Test only' },
  )
  expect(result).toEqual({ ok: true })
  expect(mocks.notification.show).toHaveBeenCalledOnce()
})
