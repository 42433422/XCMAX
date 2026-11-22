import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const headersHook = vi.hoisted(() => vi.fn())
vi.mock('electron', () => ({ session: { defaultSession: { webRequest: { onHeadersReceived: headersHook } } } }))
vi.mock('./desktop-config', () => ({ DEFAULT_PORT: 17500 }))

import { installDesktopCspDefenseInDepth } from './session-security'

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
