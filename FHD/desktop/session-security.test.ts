import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OnBeforeSendHeadersListenerDetails, Session } from 'electron'

const hook = vi.hoisted(() => vi.fn())
const headersHook = vi.hoisted(() => vi.fn())
vi.mock('electron', () => ({ session: { defaultSession: { webRequest: { onBeforeSendHeaders: hook, onHeadersReceived: headersHook } } } }))
vi.mock('./desktop-config', () => ({ DEFAULT_PORT: 17500 }))

import { desktopWorkspaceToken } from './backend-env'
import { desktopRuntime } from './runtime-state'
import { installDesktopCspDefenseInDepth, installDesktopWorkspaceCapability } from './session-security'

const origin = 'http://127.0.0.1:17500'

describe('desktop CSP response preservation', () => {
  function receive(responseHeaders: Record<string, string[]>) {
    installDesktopCspDefenseInDepth()
    const callback = vi.fn()
    headersHook.mock.lastCall![0]({ url: `${origin}/`, resourceType: 'mainFrame', responseHeaders }, callback)
    return callback.mock.calls[0][0].responseHeaders
  }

  it.each<Record<string, string[]>>([
    { 'Content-Security-Policy': ["script-src 'nonce-response-only'"] },
    { 'content-security-policy': ["script-src 'none'", "frame-ancestors 'none'"] },
    { 'Content-Security-Policy': [''], 'CONTENT-SECURITY-POLICY': ["script-src 'none'"] },
  ])('keeps every existing enforced policy without substituting fallback: %j', headers => {
    const original = structuredClone(headers)
    expect(receive(headers)).toEqual(original)
  })

  it.each<Record<string, string[]>>([{}, { 'Content-Security-Policy': ['', ' \t'] }, { 'Content-Security-Policy-Report-Only': ["script-src 'none'"] }])(
    'adds fallback when no nonempty enforced CSP exists: %j', headers => {
      expect(receive(headers)['Content-Security-Policy']).toEqual([expect.stringContaining("default-src 'self'")])
    },
  )
})

beforeEach(() => {
  desktopRuntime.backendProcess = { pid: 123, exitCode: null, signalCode: null } as NonNullable<typeof desktopRuntime.backendProcess>
  desktopRuntime.verifiedBackendProcess = desktopRuntime.backendProcess
})
function windowFixture(id = 1, url = `${origin}/local-workspace`) {
  return {
    isDestroyed: () => false,
    webContents: { id, mainFrame: { url } },
  } as NonNullable<typeof desktopRuntime.mainWindow>
}

function request(overrides: Partial<OnBeforeSendHeadersListenerDetails> = {}) {
  const main = desktopRuntime.mainWindow ?? windowFixture()
  desktopRuntime.mainWindow = main
  installDesktopWorkspaceCapability()
  const callback = vi.fn()
  hook.mock.lastCall![0]({
    url: `${origin}/api/local-workspace/status`,
    resourceType: 'xhr', webContentsId: main.webContents.id,
    frame: main.webContents.mainFrame,
    requestHeaders: { 'X-XCAGI-Desktop-Local': '1' },
    ...overrides,
  }, callback)
  expect(callback).toHaveBeenCalledOnce()
  return callback.mock.calls[0][0].requestHeaders as Record<string, string>
}

afterEach(() => {
  desktopRuntime.backendProcess = desktopRuntime.verifiedBackendProcess = null
  desktopRuntime.mainWindow = null
  desktopRuntime.auxiliaryWindows.clear()
})

describe('main-process workspace capability', () => {
  it.each(['missing', 'unverified', 'replacement', 'exited', 'signaled'])('rejects an unverified or no longer live backend: %s', state => {
    if (state === 'missing') desktopRuntime.backendProcess = null
    if (state === 'unverified') desktopRuntime.verifiedBackendProcess = null
    if (state === 'replacement') desktopRuntime.backendProcess = { ...desktopRuntime.backendProcess! } as NonNullable<typeof desktopRuntime.backendProcess>
    if (state === 'exited') Object.assign(desktopRuntime.backendProcess!, { exitCode: 0 })
    if (state === 'signaled') Object.assign(desktopRuntime.backendProcess!, { signalCode: 'SIGTERM' })
    expect(request({ requestHeaders: { 'X-XCAGI-Workspace-Capability': desktopWorkspaceToken } })).toEqual({})
  })
  it('authenticates the owning main frame without requiring an account session', () => {
    expect(request()).toEqual({
      'X-XCAGI-Desktop-Local': '1', 'X-XCAGI-Workspace-Capability': desktopWorkspaceToken,
    })
    expect(desktopWorkspaceToken).toMatch(/^[0-9a-f]{64}$/)
  })

  it('also installs on an auxiliary isolated session and binds to its owning frame', () => {
    const separateHook = vi.fn()
    installDesktopWorkspaceCapability({ webRequest: { onBeforeSendHeaders: separateHook } } as unknown as Session)
    expect(separateHook).toHaveBeenCalledOnce()
    const aux = windowFixture(2)
    desktopRuntime.auxiliaryWindows.add(aux)
    expect(request({ webContentsId: 2, frame: aux.webContents.mainFrame })['X-XCAGI-Workspace-Capability'])
      .toBe(desktopWorkspaceToken)
  })

  it.each([
    { webContentsId: undefined }, { webContentsId: 22 }, { frame: undefined }, { frame: null },
    { frame: { url: `${origin}/local-workspace` } }, { resourceType: 'subFrame' },
    { resourceType: 'mainFrame' },
  ])('rejects missing identity, unrelated windows and child frames: %j', overrides => {
    expect(request(overrides as Partial<OnBeforeSendHeadersListenerDetails>))
      .not.toHaveProperty('X-XCAGI-Workspace-Capability')
  })

  it.each([
    'https://example.com/api/local-workspace/status',
    'http://127.0.0.1:17501/api/local-workspace/status',
    'http://127.0.0.1.evil.test:17500/api/local-workspace/status',
    'http://user@127.0.0.1:17500/api/local-workspace/status',
    `${origin}/api/local-workspace-evil/status`, `${origin}/api/local-workspace`,
    `${origin}/api/local-workspace/../other`, 'not a url',
    'http://localhost:17500/api/local-workspace/status',
  ])('never supplies the token outside the exact source origin and workspace path: %s', url => {
    expect(request({ url })).not.toHaveProperty('X-XCAGI-Workspace-Capability')
  })

  it('removes every case variant before a redirect to another origin or API', () => {
    const authenticated = request({ requestHeaders: { 'x-xcagi-workspace-capability': 'forged' } })
    expect(authenticated).toEqual({ 'X-XCAGI-Workspace-Capability': desktopWorkspaceToken })
    for (const url of ['https://example.com/receive', `${origin}/api/other`]) {
      expect(request({ url, requestHeaders: {
        ...authenticated, 'x-XCAGI-workspace-Capability': desktopWorkspaceToken, Accept: 'application/json',
      } })).toEqual({ Accept: 'application/json' })
    }
  })

  it('revokes a destroyed or navigated owner even when the destination is local', () => {
    const main = windowFixture()
    desktopRuntime.mainWindow = main
    main.isDestroyed = () => true
    expect(request()).not.toHaveProperty('X-XCAGI-Workspace-Capability')
    desktopRuntime.mainWindow = windowFixture(1, 'https://example.com/')
    expect(request()).not.toHaveProperty('X-XCAGI-Workspace-Capability')
  })
})
