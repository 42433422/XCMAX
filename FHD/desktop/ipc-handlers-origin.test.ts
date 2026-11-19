import { beforeEach, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  listeners: new Map<string, (...args: any[]) => any>(),
  secret: vi.fn(() => 'synthetic-value'),
  query: vi.fn(),
  notification: { on: vi.fn(), show: vi.fn() },
  showMain: vi.fn(),
  resizeAssistant: vi.fn(),
  moveAssistant: vi.fn(),
}))
vi.mock('electron', () => ({
  ipcMain: {
    handle: (name: string, handler: (...args: any[]) => any) => mocks.handlers.set(name, handler),
    on: (name: string, handler: (...args: any[]) => any) => mocks.listeners.set(name, handler),
    removeListener: (name: string) => mocks.listeners.delete(name),
  },
  app: { getPath: () => '/synthetic/home' }, clipboard: {}, shell: {}, dialog: {},
  Notification: Object.assign(vi.fn(function () { return mocks.notification }), { isSupported: () => true }),
}))
vi.mock('./desktop-config', () => ({ APP_NAME: 'test', DEFAULT_PORT: 18500, isDesktopPackaged: () => false, readPackagedAppVersion: vi.fn() }))
vi.mock('./window-manager', () => ({ broadcastToRenderer: vi.fn(), showMainWindow: mocks.showMain }))
vi.mock('./desktop-assistant', () => ({
  desktopAssistantUrl: () => assistantUrl,
  moveDesktopAssistant: mocks.moveAssistant,
  resizeDesktopAssistant: mocks.resizeAssistant,
}))
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

const assistantUrl = 'http://127.0.0.1:18500/desktop-assistant'

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
  mocks.listeners.clear()
  mocks.secret.mockClear()
  mocks.query.mockReset()
  mocks.showMain.mockClear()
  mocks.resizeAssistant.mockClear()
  mocks.moveAssistant.mockClear()
  desktopRuntime.assistantWindow = null
  desktopRuntime.auxiliaryWindows.clear()
  desktopRuntime.splashUrl = 'file:///trusted/splash.html'
  registerDesktopIpcHandlers()
})

it('allows only the assistant main frame to control its window and denies native secrets', async () => {
  const frame = { url: assistantUrl }
  const win = { isDestroyed: () => false, isVisible: vi.fn(() => true), webContents: { id: 27, mainFrame: frame } }
  desktopRuntime.assistantWindow = win as unknown as NonNullable<typeof desktopRuntime.assistantWindow>
  const assistant = { sender: { id: 27 }, senderFrame: frame } as unknown as IpcMainInvokeEvent
  const expand = mocks.handlers.get('xcagi:assistant-expand')!
  const move = mocks.handlers.get('xcagi:assistant-move')!
  const openMain = mocks.handlers.get('xcagi:assistant-open-main')!
  const denied = { ok: false, reason: 'untrusted_sender' }
  expect(await expand(sender(assistantUrl), true)).toEqual(denied)
  expect(await expand({ ...assistant, senderFrame: { url: assistantUrl } }, true)).toEqual(denied)
  expect(await expand(assistant, 'true')).toEqual(denied)
  expect(await move(sender(assistantUrl), 12, 34)).toEqual(denied)
  expect(await move(assistant, Infinity, 34)).toEqual(denied)
  expect(await move(assistant, 12, 50000)).toEqual(denied)
  expect(await mocks.handlers.get('xcagi:secure-get')!(assistant, 'test')).toEqual(denied)
  expect(mocks.resizeAssistant).not.toHaveBeenCalled()
  expect(mocks.moveAssistant).not.toHaveBeenCalled()
  expect(mocks.secret).not.toHaveBeenCalled()
  await expand(assistant, true)
  expect(mocks.resizeAssistant).toHaveBeenCalledWith(win, true)
  await move(assistant, -12, 34)
  expect(mocks.moveAssistant).toHaveBeenCalledWith(win, -12, 34)
  win.isVisible.mockReturnValueOnce(false)
  expect(await move(assistant, 12, 34)).toEqual(denied)
  await openMain(assistant)
  expect(mocks.showMain).toHaveBeenCalledOnce()
  frame.url = 'http://127.0.0.1:18500/'
  expect(await openMain(assistant)).toEqual(denied)
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


it('附加窗口用自己的会话 cookie 恢复登录，不消费主窗口的一次性标记', async () => {
  desktopRuntime.desktopBootstrapSessionHintAvailable = true
  desktopRuntime.auxiliaryWindows.clear()
  const frame = { url: 'http://127.0.0.1:18500/chat' }
  desktopRuntime.mainWindow = {
    isDestroyed: () => false,
    webContents: { id: 17, mainFrame: frame },
  } as unknown as NonNullable<typeof desktopRuntime.mainWindow>
  desktopRuntime.auxiliaryWindows.add({
    isDestroyed: () => false,
    webContents: { id: 44, mainFrame: frame },
  } as unknown as NonNullable<typeof desktopRuntime.mainWindow>)
  const get = vi.fn(async () => [{ name: 'session_id', value: 'aux-session' }])
  const event = { sender: { id: 44, session: { cookies: { get } } }, senderFrame: frame }
  const result = await mocks.handlers.get('xcagi:consume-bootstrap-session-hint')!(event as unknown as IpcMainInvokeEvent)
  expect(result).toBe(true)
  expect(get).toHaveBeenCalledWith({ url: 'http://127.0.0.1:18500/' })
  expect(desktopRuntime.desktopBootstrapSessionHintAvailable).toBe(true)
  get.mockResolvedValueOnce([])
  expect(await mocks.handlers.get('xcagi:consume-bootstrap-session-hint')!(event as unknown as IpcMainInvokeEvent)).toBe(false)
  desktopRuntime.auxiliaryWindows.clear()
})

it('trusted runtime can still show a native notification', async () => {
  const result = await mocks.handlers.get('xcagi:show-notification')!(
    sender('http://127.0.0.1:18500/'), { title: 'Synthetic', body: 'Test only' },
  )
  expect(result).toEqual({ ok: true })
  expect(mocks.notification.show).toHaveBeenCalledOnce()
})

it('forwards only a bounded product query and waits for the main editor receipt', async () => {
  vi.useFakeTimers()
  try {
    const mainEvent = sender('http://127.0.0.1:18500/chat')
    const send = vi.fn()
    Object.assign(desktopRuntime.mainWindow!.webContents, { send, isLoading: () => false })
    const frame = { url: assistantUrl }
    desktopRuntime.assistantWindow = { isDestroyed: () => false, webContents: { id: 27, mainFrame: frame } } as any
    const event = { sender: { id: 27 }, senderFrame: frame }
    const open = mocks.handlers.get('xcagi:assistant-open-products')!
    expect(await open(mainEvent, 'part')).toMatchObject({ ok: false })
    expect(await open(event, 'x'.repeat(501))).toMatchObject({ ok: false })
    expect(send).not.toHaveBeenCalled()
    const response = open(event, ' part ')
    expect(send).toHaveBeenCalledWith('xcagi:assistant-open-products', { requestId: expect.any(String), query: 'part' })
    const { requestId } = send.mock.calls[0][1]
    const receipt = mocks.listeners.get('xcagi:assistant-products-opened')!
    receipt(event, requestId)
    receipt({ ...mainEvent, senderFrame: { url: mainEvent.senderFrame?.url } }, requestId)
    expect(mocks.listeners.size).toBe(1)
    receipt(mainEvent, requestId)
    expect(await response).toEqual({ ok: true })
    expect(mocks.listeners.size).toBe(0)
    expect(mocks.showMain).toHaveBeenCalledOnce()
    // A signed-out main renderer has no mounted editor and produces no receipt.
    ;(mainEvent.senderFrame as { url: string }).url = 'http://127.0.0.1:18500/login'
    const unavailable = open(event, 'part')
    await vi.advanceTimersByTimeAsync(3000)
    expect(await unavailable).toEqual({ ok: false })
    expect(mocks.listeners.size).toBe(0)
  } finally { vi.useRealTimers() }
})
