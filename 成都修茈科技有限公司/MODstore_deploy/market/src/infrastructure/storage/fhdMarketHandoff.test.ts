import { beforeEach, describe, expect, it, vi } from 'vitest'
import { captureBrowserHandoff, consumeBrowserHandoff, takeBrowserHandoff } from './fhdMarketHandoff'
import { getAccessToken, getRefreshToken, setAuthTokens } from './tokenStore'

const code = 'a'.repeat(43)
const route = (fullPath: string) => ({ fullPath }) as UnsafeTestValue

beforeEach(() => {
  takeBrowserHandoff(route('/'))
  window.history.replaceState(null, '', '/')
  vi.unstubAllGlobals()
})

describe('one-use browser handoff', () => {
  it('strips code before any HTTP request and consumes it only once from memory', async () => {
    window.history.replaceState(null, '', `/market/wallet?recharge=30#xcagi_code=${code}`)
    captureBrowserHandoff()
    expect(window.location.href).not.toContain(code)
    const handoff = takeBrowserHandoff(route('/wallet?recharge=30'))!
    expect(handoff.target).toBe('/wallet?recharge=30')
    expect(takeBrowserHandoff(route('/wallet?recharge=30'))).toBeNull()
    const fetcher = vi.fn().mockImplementation(async (_url, init) => {
      expect(window.location.href).not.toContain(code)
      expect(init.headers.Authorization).toBeUndefined()
      expect(JSON.parse(init.body)).toEqual({ code, target: '/wallet?recharge=30', purpose: 'wallet' })
      return { ok: true, json: async () => ({ ok: true, access_token: 'new-user', refresh_token: 'new-refresh' }) }
    })
    vi.stubGlobal('fetch', fetcher)
    setAuthTokens({ access_token: 'previous-user', refresh_token: 'previous-refresh' })
    await consumeBrowserHandoff(handoff)
    expect(getAccessToken()).toBe('new-user')
    expect(getRefreshToken()).toBe('new-refresh')
    expect(fetcher.mock.calls[0][0]).toBe('/api/auth/browser-handoff/consume')
  })

  it.each(['?xcagi_mt=long-lived-jwt', '#xcagi_mt=long-lived-jwt', '?xcagi_code=' + code])(
    'never authenticates legacy tokens or query codes: %s',
    async (secret) => {
      window.history.replaceState(null, '', '/wallet' + secret)
      captureBrowserHandoff()
      const handoff = takeBrowserHandoff(route('/wallet'))!
      expect(handoff.code).toBe('')
      expect(window.location.href).not.toMatch(/xcagi_mt|xcagi_code/)
      const fetcher = vi.fn()
      vi.stubGlobal('fetch', fetcher)
      await expect(consumeBrowserHandoff(handoff)).rejects.toThrow()
      expect(fetcher).not.toHaveBeenCalled()
      expect(getAccessToken()).toBe('')
    },
  )

  it('cleans an invalid fragment and retains harmless business query parameters', () => {
    const handoff = takeBrowserHandoff(route('/plans?plan=svip1&xcagi_mt=secret#xcagi_code=bad'))!
    expect(handoff).toEqual({ code: '', target: '/plans?plan=svip1' })
  })

  it('does not replace the existing identity when exchange fails', async () => {
    setAuthTokens({ access_token: 'existing', refresh_token: 'existing-refresh' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    await expect(consumeBrowserHandoff({ code, target: '/wallet' })).rejects.toThrow()
    expect(getAccessToken()).toBe('existing')
    expect(getRefreshToken()).toBe('existing-refresh')
  })

  it('rejects unknown destinations without sending any credential', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    for (const target of ['https://evil.example/wallet', '//evil.example/wallet', '/admin']) {
      await expect(consumeBrowserHandoff({ code, target })).rejects.toThrow()
    }
    expect(fetcher).not.toHaveBeenCalled()
  })
})
